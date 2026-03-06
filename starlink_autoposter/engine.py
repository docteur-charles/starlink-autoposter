"""
Moteur de traitement automatique des abonnements Starlink.
Exécute les cycles de requêtes dans un thread séparé.
Utilise les cookies Firefox (lecture SQLite directe) pour les appels API.
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

# User-Agent réaliste (Firefox sur Linux)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
)


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
    Lit les cookies depuis le profil Firefox (SQLite) et envoie
    les requêtes API directement via requests (pas de Selenium).
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

        # Initialiser le gestionnaire de cookies Firefox
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

        # 1. Vérifier le profil Firefox
        if not self.browser.launch():
            self._log("Profil Firefox introuvable", "error")
            return

        # 2. Vérifier la connexion (demander le login si nécessaire)
        if not self.browser.is_logged_in():
            # Ouvrir Firefox automatiquement pour que l'utilisateur se connecte
            self.browser.open_firefox_for_login()
            self._log("Connectez-vous dans Firefox puis cliquez 'Confirmer'")
            self._emit(MSG_LOGIN_REQUIRED, None)

            # Attendre que la GUI confirme le login
            self.login_event.clear()
            self.login_event.wait()

            if not self._running:
                return

            # Fermer Firefox et relire les cookies depuis le disque
            self.browser.refresh_session()

            if not self.browser.is_logged_in():
                self._log("Cookie d'authentification toujours absent après confirmation", "error")
                self._log(
                    "Astuce : connectez-vous dans Firefox, attendez que la page "
                    "account s'affiche, puis cliquez Confirmer",
                    "warning",
                )
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
        Envoie le POST de changement de produit via l'API Starlink.
        Utilise les cookies extraits du profil Firefox (pas de Selenium).

        Retourne True si le POST a réussi, False sinon.
        """
        try:
            # Récupérer les cookies depuis le profil Firefox
            cookie_jar = self.browser.get_cookies()
            if not cookie_jar:
                self._log("   Aucun cookie disponible", "error")
                return False

            # URL de l'API de changement de produit
            post_url = (
                f"https://www.starlink.com/api/webagg/v1/public/subscriptions/line/"
                f"{target.line_id}/product/{target.product}?schedule=false"
            )

            # Headers reproduisant ceux d'un navigateur Firefox
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://www.starlink.com",
                "Referer": "https://www.starlink.com/account/home",
                "User-Agent": DEFAULT_USER_AGENT,
            }

            self._log(f"   POST {target.product} pour {target.acc_id}...")

            response = requests.post(
                post_url,
                headers=headers,
                cookies=cookie_jar,
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
                self._log(
                    "   Token expiré (401) — reconnectez-vous dans Firefox",
                    "warning",
                )
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
