"""
Moteur de traitement automatique des abonnements Starlink.
Exécute les cycles de requêtes dans un thread séparé,
gère la navigation UI Selenium et les appels API.
Communique avec la GUI via une file de messages (queue.Queue).
"""

import queue
import threading
import time
import logging
from datetime import datetime
from typing import Optional, Dict, Any

import requests
import urllib3
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from starlink_autoposter.config import AppConfig, Target
from starlink_autoposter.browser import BrowserManager

# Désactiver les warnings SSL (l'API Starlink utilise des certificats internes)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# === Types de messages émis vers la GUI ===
MSG_LOG = "log"                        # Message de log à afficher
MSG_STATUS = "status"                  # Changement de statut du moteur
MSG_STATS = "stats"                    # Mise à jour des statistiques
MSG_LOGIN_REQUIRED = "login_required"  # Demande de connexion utilisateur
MSG_CYCLE_DONE = "cycle_done"          # Cycle terminé
MSG_STOPPED = "stopped"                # Moteur arrêté


class EngineStats:
    """Statistiques d'exécution du moteur, mises à jour en temps réel."""

    def __init__(self):
        self.total_cycles: int = 0
        self.total_requests: int = 0
        self.successful: int = 0
        self.failed: int = 0
        self.start_time: datetime = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise les stats pour affichage dans la GUI."""
        uptime = datetime.now() - self.start_time
        rate = (self.successful / self.total_requests * 100) if self.total_requests > 0 else 0.0
        return {
            "cycles": self.total_cycles,
            "total": self.total_requests,
            "success": self.successful,
            "failed": self.failed,
            "rate": f"{rate:.1f}%",
            # Formater le uptime sans microsecondes
            "uptime": str(uptime).split(".")[0],
        }


class StarlinkEngine:
    """
    Moteur principal de l'application.
    Exécute les cycles de requêtes dans un thread séparé.
    Communique avec la GUI via self.message_queue.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.message_queue: queue.Queue = queue.Queue()
        self.login_event = threading.Event()
        self.stats = EngineStats()
        self.browser: Optional[BrowserManager] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        """Indique si le moteur est actuellement en cours d'exécution."""
        return self._running

    # === Communication avec la GUI ===

    def _emit(self, msg_type: str, data: Any = None):
        """Envoie un message vers la GUI via la queue thread-safe."""
        self.message_queue.put((msg_type, data))

    def _log(self, message: str, level: str = "info"):
        """Log un message et l'envoie simultanément à la GUI."""
        log_func = getattr(logger, level, logger.info)
        log_func(message)
        self._emit(MSG_LOG, {"message": message, "level": level})

    # === Contrôle du moteur ===

    def start(self):
        """Démarre le moteur dans un thread séparé (daemon)."""
        if self._running:
            return

        self._running = True
        self.stats = EngineStats()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._emit(MSG_STATUS, "running")

    def stop(self):
        """Demande l'arrêt propre du moteur."""
        self._running = False
        # Débloquer le thread s'il attend la confirmation de login
        self.login_event.set()
        self._emit(MSG_STATUS, "stopping")

    def confirm_login(self):
        """Appelé par la GUI quand l'utilisateur confirme sa connexion dans Firefox."""
        self.login_event.set()

    # === Boucle principale ===

    def _run_loop(self):
        """
        Boucle principale du moteur.
        Exécute les cycles puis attend l'intervalle configuré.
        """
        self._log("Moteur démarré")

        # Initialiser le gestionnaire de navigateur
        self.browser = BrowserManager(
            profile_name=self.config.firefox_profile,
            log_callback=self._log,
        )

        while self._running:
            self._execute_cycle()

            if not self._running:
                break

            # Émettre les statistiques après chaque cycle
            self._emit(MSG_STATS, self.stats.to_dict())
            self._emit(MSG_CYCLE_DONE, None)

            # Attente entre les cycles (interruptible seconde par seconde)
            wait_seconds = self.config.interval_minutes * 60
            self._log(f"Prochain cycle dans {self.config.interval_minutes} minutes...")
            self._emit(MSG_STATUS, "waiting")

            for elapsed in range(wait_seconds):
                if not self._running:
                    break
                time.sleep(1)

                # Mettre à jour le temps restant toutes les 30 secondes
                remaining = wait_seconds - elapsed - 1
                if remaining > 0 and remaining % 30 == 0:
                    self._emit(MSG_STATUS, f"waiting:{remaining}")

        # Nettoyage à l'arrêt
        if self.browser:
            self.browser.quit()

        self._log("Moteur arrêté")
        self._emit(MSG_STOPPED, None)
        self._emit(MSG_STATUS, "stopped")

    # === Exécution d'un cycle ===

    def _execute_cycle(self):
        """Exécute un cycle complet : traite toutes les cibles séquentiellement."""
        cycle_num = self.stats.total_cycles + 1
        self._log(f"=== Cycle {cycle_num} ===")
        self._emit(MSG_STATUS, "running")

        # 1. Lancer Firefox
        if not self.browser.launch():
            self._log("Impossible de lancer Firefox", "error")
            return

        # 2. Vérifier la connexion (demander le login si nécessaire)
        if not self.browser.is_logged_in():
            self._log("Connexion requise — veuillez vous connecter dans Firefox")
            self._emit(MSG_LOGIN_REQUIRED, None)

            # Attendre que la GUI confirme le login
            self.login_event.clear()
            self.login_event.wait()

            if not self._running:
                return

            # Rafraîchir les cookies après login
            self.browser.refresh_session()

            if not self.browser.is_logged_in():
                self._log("Connexion échouée après confirmation", "error")
                return

        # 3. Traiter les cibles
        targets = self.config.get_targets()
        if not targets:
            self._log("Aucune cible configurée", "warning")
            return

        ok, ko = 0, 0
        start = time.time()

        for idx, target in enumerate(targets, 1):
            if not self._running:
                break

            self._log(
                f"[{idx}/{len(targets)}] {target.acc_id} | "
                f"{target.line_id[:8]}... | {target.product}"
            )

            success = self._process_account(target)
            if success:
                ok += 1
                self.stats.successful += 1
            else:
                ko += 1
                self.stats.failed += 1

            self.stats.total_requests += 1

            # Pause anti-burst entre les cibles (2 secondes)
            time.sleep(2)

        self.stats.total_cycles += 1
        elapsed = time.time() - start
        self._log(f"Cycle {cycle_num} terminé : {ok} OK / {ko} KO en {elapsed:.1f}s")

    # === Traitement d'un compte individuel ===

    def _process_account(self, target: Target) -> bool:
        """
        Traite un compte via la séquence d'automatisation UI :
        1. Naviguer vers account/home
        2. Cliquer sur l'avatar utilisateur
        3. Ouvrir le sélecteur de compte
        4. Sélectionner le kit par ACC-ID
        5. Cliquer sur "Votre abonnement"
        6. Envoyer le POST de changement de produit via requests

        Retourne True si le POST a réussi, False sinon.
        """
        driver = self.browser.driver
        if not driver:
            self._log("   Navigateur non disponible", "error")
            return False

        try:
            wait = WebDriverWait(driver, 15)

            # --- Étape 1 : Navigation vers account/home ---
            self._log("   Étape 1 : Navigation account/home")
            driver.get("https://www.starlink.com/account/home")
            time.sleep(5)

            # --- Étape 2 : Clic sur l'avatar utilisateur ---
            self._log("   Étape 2 : Clic avatar")
            try:
                avatar = wait.until(EC.element_to_be_clickable((
                    By.CSS_SELECTOR,
                    "button[aria-label='user profile'], "
                    "div.MuiAvatar-root.MuiAvatar-circular"
                )))
                driver.execute_script("arguments[0].click();", avatar)
                time.sleep(2)
            except Exception:
                self._log("   Avatar non trouvé, poursuite...", "warning")

            # --- Étape 3 : Ouvrir le sélecteur de compte (combobox MUI) ---
            self._log("   Étape 3 : Sélecteur de compte")
            try:
                combobox_selectors = [
                    "li[role='combobox']",
                    "li.MuiMenuItem-root[role='combobox']",
                    "li.MuiButtonBase-root.MuiMenuItem-root",
                ]
                combobox = None
                for sel in combobox_selectors:
                    try:
                        combobox = driver.find_element(By.CSS_SELECTOR, sel)
                        if combobox:
                            break
                    except Exception:
                        continue

                if combobox:
                    driver.execute_script("arguments[0].click();", combobox)
                    time.sleep(2)
                else:
                    self._log("   Sélecteur de compte non trouvé, poursuite...", "warning")

            except Exception as e:
                self._log(f"   Erreur sélecteur de compte : {e}", "warning")

            # --- Étape 4 : Sélectionner le kit par ACC-ID dans la liste déroulante ---
            self._log(f"   Étape 4 : Recherche kit {target.acc_id}")
            try:
                # Sélecteurs XPath pour trouver le kit dans le menu MUI
                kit_selectors = [
                    f"//li[contains(@class, 'MuiMenuItem-root')][.//p[contains(text(), '{target.acc_id}')]]",
                    f"//li[contains(@class, 'MuiButtonBase-root')][.//p[contains(text(), '{target.acc_id}')]]",
                    f"//li[contains(., '{target.acc_id}')]",
                    f"//*[contains(text(), '{target.acc_id}')]/ancestor::li",
                ]
                kit_elem = None
                for sel in kit_selectors:
                    try:
                        kit_elem = driver.find_element(By.XPATH, sel)
                        if kit_elem:
                            break
                    except Exception:
                        continue

                if kit_elem:
                    driver.execute_script("arguments[0].click();", kit_elem)
                    time.sleep(3)
                else:
                    self._log(f"   Kit {target.acc_id} non trouvé dans la liste", "warning")
                    return False

            except Exception as e:
                self._log(f"   Erreur sélection kit : {e}", "warning")

            # --- Étape 5 : Cliquer sur "Votre abonnement" ---
            self._log("   Étape 5 : Votre abonnement")
            abonnement_selectors = [
                "//p[contains(text(), 'Votre abonnement')]",
                "//div[contains(., 'Votre abonnement') and contains(., 'Gérer le service')]",
                "//*[contains(text(), 'Votre abonnement')]",
            ]
            abonnement_elem = None
            for sel in abonnement_selectors:
                try:
                    abonnement_elem = wait.until(
                        EC.element_to_be_clickable((By.XPATH, sel))
                    )
                    if abonnement_elem:
                        break
                except Exception:
                    continue

            if not abonnement_elem:
                self._log("   'Votre abonnement' non trouvé", "warning")
                return False

            driver.execute_script("arguments[0].click();", abonnement_elem)
            time.sleep(3)

            # --- Étape 6 : POST de changement de produit via requests ---
            current_url = driver.current_url
            self._log("   Étape 6 : POST changement de produit")

            post_url = (
                f"https://www.starlink.com/api/webagg/v1/public/subscriptions/line/"
                f"{target.line_id}/product/{target.product}?schedule=false"
            )

            # Créer une session requests avec les cookies du navigateur
            session = requests.Session()
            for cookie in driver.get_cookies():
                session.cookies.set(
                    cookie["name"],
                    cookie["value"],
                    domain=cookie.get("domain", ".starlink.com"),
                )

            # Headers identiques à ceux du navigateur
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://www.starlink.com",
                "Referer": current_url,
                "User-Agent": driver.execute_script("return navigator.userAgent;"),
            }

            response = session.post(
                post_url,
                headers=headers,
                json={},
                verify=False,
                timeout=self.config.timeout_seconds,
            )

            # Analyser la réponse
            status = response.status_code

            if status in (200, 201, 202, 204):
                self._log(f"   POST réussi ({status})")
                return True
            elif status == 401:
                self._log("   Token expiré (401) — rafraîchissement nécessaire", "warning")
                self.browser.refresh_session()
                return False
            elif status == 403:
                self._log(f"   Accès refusé (403) : {response.text[:200]}", "warning")
                return False
            else:
                self._log(f"   Réponse inattendue : {status}", "warning")
                if len(response.text) < 200:
                    self._log(f"   Détail : {response.text}")
                return False

        except Exception as e:
            self._log(f"   Erreur traitement : {e}", "error")
            return False
