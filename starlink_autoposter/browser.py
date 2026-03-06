"""
Gestion des cookies Firefox pour l'authentification Starlink.
Lit les cookies directement depuis la base SQLite du profil Firefox,
sans utiliser Selenium (évite la détection hCaptcha/Cloudflare).
Ouvre Firefox en mode normal pour la connexion manuelle.
"""

import glob
import os
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import time
import logging
from typing import Optional, Callable, List, Dict

import requests

logger = logging.getLogger(__name__)

# Type du callback de log : (message, level) -> None
LogCallback = Callable[[str, str], None]


def _default_log(message: str, level: str = "info"):
    """Callback de log par défaut (utilise le logger standard)."""
    log_func = getattr(logger, level, logger.info)
    log_func(message)


class BrowserManager:
    """
    Gestionnaire des cookies Firefox pour Starlink.
    Lit les cookies d'authentification directement depuis cookies.sqlite
    du profil Firefox, sans passer par Selenium.
    """

    def __init__(self, profile_name: str = "starlink", log_callback: Optional[LogCallback] = None):
        self.profile_name = profile_name
        self._log = log_callback or _default_log
        self._profile_path: Optional[str] = None
        self._firefox_process: Optional[subprocess.Popen] = None

    def _get_firefox_base_dirs(self) -> list:
        """
        Retourne la liste des répertoires possibles contenant les profils Firefox.
        Gère les installations classiques, Snap et Flatpak.
        """
        home = os.path.expanduser("~")

        if os.name == "nt":
            # Windows
            return [os.path.join(home, r"AppData\Roaming\Mozilla\Firefox\Profiles")]

        # Linux / macOS : plusieurs emplacements possibles
        return [
            os.path.join(home, ".mozilla", "firefox"),                            # Installation classique (apt, .deb)
            os.path.join(home, "snap", "firefox", "common", ".mozilla", "firefox"),  # Snap (Ubuntu 22.04+)
            os.path.join(home, ".var", "app", "org.mozilla.firefox", ".mozilla", "firefox"),  # Flatpak
        ]

    def _find_profile_path(self) -> Optional[str]:
        """
        Recherche le chemin du profil Firefox correspondant au nom configuré.
        Parcourt tous les emplacements possibles (classique, Snap, Flatpak).
        """
        if self._profile_path and os.path.isdir(self._profile_path):
            return self._profile_path

        tried_dirs = []

        for base in self._get_firefox_base_dirs():
            if not os.path.isdir(base):
                tried_dirs.append(base)
                continue

            matches = glob.glob(os.path.join(base, f"*{self.profile_name}*"))
            if matches:
                self._log(f"Profil Firefox trouvé : {matches[0]}")
                self._profile_path = matches[0]
                return matches[0]

            tried_dirs.append(base)

        self._log(
            f"Profil Firefox '{self.profile_name}' non trouvé. "
            f"Emplacements vérifiés : {', '.join(tried_dirs)}. "
            "Créez un profil Firefox nommé ainsi via about:profiles "
            "ou changez le nom dans la configuration.",
            "warning",
        )
        return None

    def _read_cookies_from_sqlite(self, profile_path: str) -> List[Dict]:
        """
        Lit les cookies Starlink depuis le fichier cookies.sqlite du profil Firefox.
        Copie le fichier dans un répertoire temporaire pour éviter les conflits
        de verrouillage si Firefox est ouvert.
        """
        cookies_db = os.path.join(profile_path, "cookies.sqlite")
        if not os.path.isfile(cookies_db):
            self._log(f"Fichier cookies.sqlite introuvable dans {profile_path}", "error")
            return []

        cookies = []
        tmp_path = None

        try:
            # Copier le fichier pour éviter le verrou SQLite de Firefox
            tmp_dir = tempfile.mkdtemp()
            tmp_path = os.path.join(tmp_dir, "cookies.sqlite")
            shutil.copy2(cookies_db, tmp_path)

            conn = sqlite3.connect(tmp_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Extraire les cookies du domaine starlink.com non expirés
            cursor.execute(
                "SELECT name, value, host, path, expiry, isSecure, isHttpOnly "
                "FROM moz_cookies WHERE host LIKE '%starlink.com%'"
            )

            now = int(time.time())
            for row in cursor.fetchall():
                # Ignorer les cookies expirés (expiry=0 = session, donc valide)
                if row["expiry"] != 0 and row["expiry"] < now:
                    continue
                cookies.append({
                    "name": row["name"],
                    "value": row["value"],
                    "domain": row["host"],
                    "path": row["path"],
                    "secure": bool(row["isSecure"]),
                })

            conn.close()
            self._log(f"{len(cookies)} cookies Starlink extraits du profil Firefox")

        except Exception as e:
            self._log(f"Erreur lecture cookies.sqlite : {e}", "error")

        finally:
            # Nettoyer le fichier temporaire
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                    os.rmdir(os.path.dirname(tmp_path))
                except OSError:
                    pass

        return cookies

    def launch(self) -> bool:
        """
        Vérifie que le profil Firefox existe.
        Retourne True si le profil est accessible.
        """
        profile_path = self._find_profile_path()
        if not profile_path:
            self._log("Impossible de trouver le profil Firefox", "error")
            return False

        self._log("Profil Firefox prêt")
        return True

    def open_firefox_for_login(self):
        """
        Ouvre Firefox en mode normal (pas Selenium) avec le profil configuré
        pour que l'utilisateur puisse se connecter manuellement sur starlink.com.
        Firefox normal n'est pas détecté par hCaptcha.
        """
        profile_path = self._find_profile_path()
        if not profile_path:
            return

        # Fermer une instance précédente si elle existe
        self._close_firefox()

        try:
            self._log("Ouverture de Firefox pour connexion manuelle...")
            self._firefox_process = subprocess.Popen(
                [
                    "firefox",
                    "-profile", profile_path,
                    "https://www.starlink.com/account",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._log("Firefox ouvert — connectez-vous puis cliquez 'Confirmer'")
        except FileNotFoundError:
            self._log(
                "Firefox introuvable. Installez Firefox et connectez-vous "
                "manuellement sur starlink.com",
                "error",
            )
        except Exception as e:
            self._log(f"Erreur ouverture Firefox : {e}", "error")

    def _close_firefox(self):
        """Ferme proprement l'instance Firefox ouverte par l'app."""
        if self._firefox_process and self._firefox_process.poll() is None:
            try:
                # SIGTERM pour un arrêt propre (flush des cookies sur disque)
                self._firefox_process.terminate()
                self._firefox_process.wait(timeout=10)
                self._log("Firefox fermé (cookies sauvegardés)")
            except subprocess.TimeoutExpired:
                self._firefox_process.kill()
                self._log("Firefox forcé à se fermer", "warning")
            except Exception:
                pass
            self._firefox_process = None

    def is_logged_in(self) -> bool:
        """Vérifie si le cookie d'authentification Starlink existe dans le profil."""
        profile_path = self._find_profile_path()
        if not profile_path:
            return False

        cookies = self._read_cookies_from_sqlite(profile_path)

        # Chercher le cookie d'auth Starlink (plusieurs noms possibles)
        auth_keywords = ["access", "token", "auth"]
        auth_cookie = None
        for c in cookies:
            name_lower = c["name"].lower()
            # Ignorer les cookies OIDC intermédiaires (nonce, correlation)
            if "nonce" in name_lower or "correlation" in name_lower:
                continue
            if any(kw in name_lower for kw in auth_keywords):
                auth_cookie = c["name"]
                break

        if auth_cookie:
            self._log(f"Cookie d'authentification trouvé : {auth_cookie}")
            return True

        # Debug : afficher les noms de cookies pour diagnostiquer
        cookie_names = [c["name"] for c in cookies]
        self._log(
            f"Cookie d'authentification absent. "
            f"Cookies trouvés : {', '.join(cookie_names)}",
            "warning",
        )
        return False

    def get_cookies(self) -> requests.cookies.RequestsCookieJar:
        """
        Extrait les cookies Starlink du profil Firefox pour la bibliothèque requests.
        Retourne un CookieJar vide si le profil n'est pas disponible.
        """
        cj = requests.cookies.RequestsCookieJar()
        profile_path = self._find_profile_path()
        if not profile_path:
            return cj

        for cookie in self._read_cookies_from_sqlite(profile_path):
            cj.set(
                cookie["name"],
                cookie["value"],
                domain=cookie["domain"],
                path=cookie["path"],
            )

        return cj

    def refresh_session(self):
        """
        Ferme Firefox (pour flush des cookies) puis relit depuis le profil.
        """
        # Fermer Firefox pour que les cookies soient écrits sur disque
        self._close_firefox()
        # Attendre un instant pour que le fichier soit libéré
        time.sleep(2)

        self._log("Relecture des cookies depuis le profil Firefox...")
        profile_path = self._find_profile_path()
        if profile_path:
            cookies = self._read_cookies_from_sqlite(profile_path)
            if cookies:
                self._log(f"Session rafraîchie : {len(cookies)} cookies")
            else:
                self._log("Aucun cookie trouvé — reconnectez-vous dans Firefox", "warning")

    def quit(self):
        """Ferme Firefox si ouvert et nettoie."""
        self._close_firefox()
        self._log("Session terminée")
