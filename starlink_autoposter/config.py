"""
Gestion de la configuration persistante de l'application.
Sauvegarde et charge les paramètres depuis un fichier JSON local
dans le répertoire ~/.starlink-autoposter/.
"""

import json
import os
from dataclasses import dataclass, field
from typing import List, Dict

# Nom du fichier de configuration
CONFIG_FILENAME = "starlink_config.json"


def get_config_dir() -> str:
    """Retourne le répertoire de configuration de l'application."""
    config_dir = os.path.join(os.path.expanduser("~"), ".starlink-autoposter")
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


def get_config_path() -> str:
    """Retourne le chemin absolu du fichier de configuration."""
    return os.path.join(get_config_dir(), CONFIG_FILENAME)


def get_log_path() -> str:
    """Retourne le chemin du fichier de log."""
    return os.path.join(get_config_dir(), "starlink_autoposter.log")


@dataclass
class Target:
    """
    Représente une cible de changement d'abonnement Starlink.
    Chaque cible correspond à un kit/compte avec un produit à appliquer.
    """
    acc_id: str      # Identifiant du compte (ex: ACC-DF-10065240-90193-36)
    line_id: str     # UUID de la ligne de service
    product: str     # Identifiant du produit cible (ex: ht-consumer-subscription-rv)

    def to_dict(self) -> Dict[str, str]:
        """Sérialise la cible en dictionnaire pour JSON."""
        return {"acc_id": self.acc_id, "line_id": self.line_id, "product": self.product}

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "Target":
        """Crée une cible depuis un dictionnaire JSON."""
        return cls(
            acc_id=data.get("acc_id", ""),
            line_id=data.get("line_id", ""),
            product=data.get("product", ""),
        )


@dataclass
class AppConfig:
    """
    Configuration globale de l'application.
    Tous les paramètres sont persistés dans un fichier JSON.
    """
    interval_minutes: int = 15          # Intervalle entre les cycles (minutes)
    timeout_seconds: int = 15           # Timeout des requêtes HTTP (secondes)
    max_workers: int = 10               # Nombre max de workers parallèles (réservé pour usage futur)
    firefox_profile: str = "starlink"   # Nom du profil Firefox à utiliser
    targets: List[Dict[str, str]] = field(default_factory=list)

    def get_targets(self) -> List[Target]:
        """Retourne les cibles sous forme d'objets Target."""
        return [Target.from_dict(t) for t in self.targets]

    def set_targets(self, targets: List[Target]):
        """Met à jour les cibles depuis une liste d'objets Target."""
        self.targets = [t.to_dict() for t in targets]

    def save(self):
        """Sauvegarde la configuration dans le fichier JSON."""
        path = get_config_path()
        data = {
            "interval_minutes": self.interval_minutes,
            "timeout_seconds": self.timeout_seconds,
            "max_workers": self.max_workers,
            "firefox_profile": self.firefox_profile,
            "targets": self.targets,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls) -> "AppConfig":
        """
        Charge la configuration depuis le fichier JSON.
        Retourne les valeurs par défaut si le fichier n'existe pas ou est invalide.
        """
        path = get_config_path()
        if not os.path.exists(path):
            return cls()

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Ne garder que les clés connues pour éviter les erreurs
            valid_keys = cls.__dataclass_fields__.keys()
            filtered = {k: v for k, v in data.items() if k in valid_keys}
            return cls(**filtered)
        except (json.JSONDecodeError, TypeError, KeyError):
            return cls()
