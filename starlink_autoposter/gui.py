"""
Interface graphique de l'application Starlink AutoPoster.
Utilise customtkinter pour un rendu moderne en thème sombre.
Communique avec le moteur (engine) via une queue thread-safe.

Saadaw Systems - Architectes du Numérique
"""

import os
import queue
import re
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from typing import Optional, List

import customtkinter as ctk
from PIL import Image

from starlink_autoposter import (
    __version__,
    __app_name__,
    __company__,
    __company_url__,
    __company_email__,
    __company_slogan__,
    get_asset_path,
)
from starlink_autoposter.config import AppConfig, Target
from starlink_autoposter.engine import (
    StarlinkEngine,
    MSG_LOG,
    MSG_STATUS,
    MSG_STATS,
    MSG_LOGIN_REQUIRED,
    MSG_CYCLE_DONE,
    MSG_STOPPED,
)

# Thème sombre par défaut
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# === Palette Saadaw Systems (issue du logo) ===
COLOR_GOLD = "#C9A84C"           # Or principal (accents, boutons primaires)
COLOR_GOLD_HOVER = "#D4A848"     # Or clair au survol
COLOR_GOLD_DARK = "#B08D3E"      # Or foncé (texte secondaire)
COLOR_DARK = "#1a1e2a"           # Charbon foncé (fond du logo)
COLOR_LIGHT = "#f5f3ef"          # Blanc cassé (fond clair du chip)

# Couleurs fonctionnelles
COLOR_SUCCESS = "#27ae60"
COLOR_SUCCESS_HOVER = "#2ecc71"
COLOR_DANGER = "#c0392b"
COLOR_DANGER_HOVER = "#e74c3c"
COLOR_WARNING = "#f39c12"

# Intervalle de polling de la queue (en ms)
POLL_INTERVAL_MS = 100


def _open_url(url: str):
    """Ouvre une URL dans le navigateur par défaut du système."""
    import webbrowser
    webbrowser.open(url)


# ============================================================
# Dialogue : Ajouter / Modifier une cible
# ============================================================

class TargetDialog(ctk.CTkToplevel):
    """Fenêtre modale pour ajouter ou modifier une cible."""

    def __init__(self, parent, target: Optional[Target] = None):
        super().__init__(parent)
        self.title("Ajouter une cible" if not target else "Modifier la cible")
        self.geometry("550x280")
        self.resizable(False, False)
        self.result: Optional[Target] = None

        # Contenu du formulaire
        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        # ACC ID
        ctk.CTkLabel(frame, text="ACC ID :").grid(row=0, column=0, sticky="w", pady=8)
        self.acc_entry = ctk.CTkEntry(frame, width=380, placeholder_text="ACC-DF-10065240-90193-36")
        self.acc_entry.grid(row=0, column=1, pady=8, padx=(10, 0))

        # Line ID (UUID)
        ctk.CTkLabel(frame, text="Line ID :").grid(row=1, column=0, sticky="w", pady=8)
        self.line_entry = ctk.CTkEntry(frame, width=380, placeholder_text="787a0495-0788-4438-9525-1874133aa951")
        self.line_entry.grid(row=1, column=1, pady=8, padx=(10, 0))

        # Produit
        ctk.CTkLabel(frame, text="Produit :").grid(row=2, column=0, sticky="w", pady=8)
        self.product_entry = ctk.CTkEntry(frame, width=380, placeholder_text="ht-consumer-subscription-rv")
        self.product_entry.grid(row=2, column=1, pady=8, padx=(10, 0))

        # Pré-remplir si modification
        if target:
            self.acc_entry.insert(0, target.acc_id)
            self.line_entry.insert(0, target.line_id)
            self.product_entry.insert(0, target.product)

        # Boutons Annuler / Valider
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.grid(row=3, column=0, columnspan=2, pady=(20, 0))

        ctk.CTkButton(
            btn_frame, text="Annuler", command=self.destroy,
            fg_color="gray", width=100,
        ).pack(side="left", padx=10)
        ctk.CTkButton(
            btn_frame, text="Valider", command=self._validate,
            fg_color=COLOR_SUCCESS, hover_color=COLOR_SUCCESS_HOVER, width=100,
        ).pack(side="left", padx=10)

        # Modale : transient + grab différé (fix fenêtre vide sur Linux)
        self.transient(parent)
        self.after(150, self._activate)

    def _activate(self):
        """Active le focus modal après le rendu complet de la fenêtre."""
        self.lift()
        self.focus_force()
        self.grab_set()
        self.acc_entry.focus()

    def _validate(self):
        """Valide les champs et ferme le dialogue."""
        acc = self.acc_entry.get().strip()
        line = self.line_entry.get().strip()
        product = self.product_entry.get().strip()

        if not all([acc, line, product]):
            messagebox.showwarning(
                "Champs requis",
                "Tous les champs sont obligatoires.",
                parent=self,
            )
            return

        self.result = Target(acc_id=acc, line_id=line, product=product)
        self.destroy()


# ============================================================
# Dialogue : Importer des cibles depuis des URLs
# ============================================================

class ImportDialog(ctk.CTkToplevel):
    """Fenêtre modale pour importer des cibles depuis des URLs Starlink."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Importer depuis des URLs")
        self.geometry("650x450")
        self.result: List[Target] = []

        # Instructions
        ctk.CTkLabel(
            self,
            text="Collez les URLs Starlink (une par ligne) :",
            font=ctk.CTkFont(size=13),
        ).pack(padx=20, pady=(15, 5), anchor="w")

        ctk.CTkLabel(
            self,
            text="Format attendu : .../line/{uuid}/product/{product-id}",
            text_color="gray",
            font=ctk.CTkFont(size=11),
        ).pack(padx=20, anchor="w")

        # Zone de texte pour les URLs
        self.text = ctk.CTkTextbox(self, height=220)
        self.text.pack(fill="both", expand=True, padx=20, pady=(5, 10))

        # ACC ID commun (optionnel)
        acc_frame = ctk.CTkFrame(self, fg_color="transparent")
        acc_frame.pack(fill="x", padx=20)

        ctk.CTkLabel(acc_frame, text="ACC ID commun (optionnel) :").pack(side="left")
        self.acc_entry = ctk.CTkEntry(acc_frame, width=350, placeholder_text="ACC-DF-...")
        self.acc_entry.pack(side="left", padx=(10, 0))

        # Boutons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=15)

        ctk.CTkButton(
            btn_frame, text="Annuler", command=self.destroy,
            fg_color="gray", width=100,
        ).pack(side="left", padx=10)
        ctk.CTkButton(
            btn_frame, text="Importer", command=self._do_import,
            fg_color=COLOR_SUCCESS, hover_color=COLOR_SUCCESS_HOVER, width=100,
        ).pack(side="left", padx=10)

        # Modale : transient + grab différé (fix fenêtre vide sur Linux)
        self.transient(parent)
        self.after(150, self._activate)

    def _activate(self):
        """Active le focus modal après le rendu complet de la fenêtre."""
        self.lift()
        self.focus_force()
        self.grab_set()

    def _do_import(self):
        """Parse les URLs et extrait les cibles."""
        text = self.text.get("1.0", "end").strip()
        acc_id = self.acc_entry.get().strip() or "N/A"

        # Extraire line_id et product depuis chaque URL
        url_pattern = re.compile(r"/line/([a-f0-9-]+)/product/([^/?\s]+)")

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            match = url_pattern.search(line)
            if match:
                self.result.append(Target(
                    acc_id=acc_id,
                    line_id=match.group(1),
                    product=match.group(2),
                ))

        if not self.result:
            messagebox.showwarning(
                "Aucune URL valide",
                "Aucune URL au format .../line/.../product/... trouvée.",
                parent=self,
            )
            return

        messagebox.showinfo(
            "Importation",
            f"{len(self.result)} cible(s) importée(s).",
            parent=self,
        )
        self.destroy()


# ============================================================
# Fenêtre principale
# ============================================================

class App(ctk.CTk):
    """
    Fenêtre principale de l'application Starlink AutoPoster.
    Contient les onglets Cibles, Configuration, Journal et Statistiques.
    """

    def __init__(self):
        super().__init__()

        self.title(f"{__app_name__} v{__version__} - {__company__}")
        self.geometry("950x680")
        self.minsize(800, 550)

        # Charger l'icône de l'application (logo Saadaw Systems)
        self._load_icon()

        # Charger la configuration persistante
        self.config = AppConfig.load()
        self.engine: Optional[StarlinkEngine] = None

        # Construire l'interface
        self._build_header()
        self._build_tabs()

        # Lancer le polling de la queue du moteur
        self._poll_messages()

        # Gérer la fermeture propre de la fenêtre
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _load_icon(self):
        """Charge le logo Saadaw Systems comme icône de la fenêtre et du header."""
        from PIL import ImageTk
        self._header_logo = None
        self._icon_refs = []  # Garder les références pour éviter le garbage collection

        try:
            icon_path = get_asset_path("icon.png")
            if not os.path.exists(icon_path):
                return

            pil_image = Image.open(icon_path)

            # Icône de la barre de titre (plusieurs tailles pour compatibilité WM)
            for size in (64, 32, 16):
                resized = pil_image.resize((size, size), Image.LANCZOS)
                photo = ImageTk.PhotoImage(resized)
                self._icon_refs.append(photo)

            self.iconphoto(True, *self._icon_refs)

            # Image pour le header (CTkImage avec Pillow)
            self._header_logo = ctk.CTkImage(
                light_image=pil_image,
                dark_image=pil_image,
                size=(40, 40),
            )
        except Exception as e:
            print(f"Erreur chargement icône : {e}")
            self._header_logo = None

    # ========================================
    # En-tête avec contrôles Start/Stop
    # ========================================

    def _build_header(self):
        """Construit la barre supérieure avec logo, titre, boutons et statut."""
        header = ctk.CTkFrame(self, height=60)
        header.pack(fill="x", padx=10, pady=(10, 0))
        header.pack_propagate(False)

        # Logo Saadaw Systems (si disponible)
        if self._header_logo:
            ctk.CTkLabel(header, image=self._header_logo, text="").pack(
                side="left", padx=(15, 5),
            )

        # Bloc titre + sous-titre
        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.pack(side="left", padx=(0, 15))

        ctk.CTkLabel(
            title_frame,
            text=__app_name__,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_frame,
            text=f"{__company__} - {__company_slogan__}",
            font=ctk.CTkFont(size=10),
            text_color=COLOR_GOLD,
        ).pack(anchor="w")

        # Bouton "A propos" (discret, tout a droite)
        ctk.CTkButton(
            header, text="?", command=self._show_about,
            width=30, height=30, corner_radius=15,
            fg_color=COLOR_GOLD, hover_color=COLOR_GOLD_HOVER,
            text_color=COLOR_DARK,
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="right", padx=(5, 10), pady=10)

        # Bouton Arreter (desactive au depart)
        self.stop_btn = ctk.CTkButton(
            header, text="Arreter", command=self._stop_engine,
            fg_color=COLOR_DANGER, hover_color=COLOR_DANGER_HOVER,
            state="disabled", width=100,
        )
        self.stop_btn.pack(side="right", padx=5, pady=10)

        # Bouton Demarrer
        self.start_btn = ctk.CTkButton(
            header, text="Demarrer", command=self._start_engine,
            fg_color=COLOR_GOLD, hover_color=COLOR_GOLD_HOVER,
            text_color=COLOR_DARK,
            font=ctk.CTkFont(weight="bold"),
            width=100,
        )
        self.start_btn.pack(side="right", padx=5, pady=10)

        # Indicateur de statut
        self.status_label = ctk.CTkLabel(
            header, text="En attente", text_color="gray",
            font=ctk.CTkFont(size=13),
        )
        self.status_label.pack(side="right", padx=15)

    # ========================================
    # Système d'onglets
    # ========================================

    def _build_tabs(self):
        """Construit les 4 onglets de l'interface."""
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)

        self._build_targets_tab()
        self._build_config_tab()
        self._build_log_tab()
        self._build_stats_tab()

    # ========================================
    # Onglet Cibles
    # ========================================

    def _build_targets_tab(self):
        """Onglet de gestion des cibles (ajout, modification, suppression)."""
        tab = self.tabview.add("Cibles")

        # Barre d'outils
        toolbar = ctk.CTkFrame(tab, fg_color="transparent")
        toolbar.pack(fill="x", padx=5, pady=5)

        ctk.CTkButton(
            toolbar, text="+ Ajouter", command=self._add_target, width=100,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            toolbar, text="Importer URLs", command=self._import_urls, width=120,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            toolbar, text="Modifier", command=self._edit_target_btn, width=100,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            toolbar, text="Dupliquer", command=self._duplicate_target, width=100,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            toolbar, text="Supprimer", command=self._delete_target,
            width=100, fg_color=COLOR_DANGER, hover_color=COLOR_DANGER_HOVER,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            toolbar, text="Tout supprimer", command=self._clear_targets,
            width=120, fg_color=COLOR_DANGER, hover_color=COLOR_DANGER_HOVER,
        ).pack(side="left", padx=2)

        # Compteur de cibles
        self.target_count_label = ctk.CTkLabel(toolbar, text="0 cible(s)")
        self.target_count_label.pack(side="right", padx=10)

        # Tableau des cibles (ttk.Treeview pour le support des colonnes)
        tree_frame = ctk.CTkFrame(tab)
        tree_frame.pack(fill="both", expand=True, padx=5, pady=5)

        columns = ("acc_id", "line_id", "product")
        self.target_tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="extended",
        )
        self.target_tree.heading("acc_id", text="ACC ID")
        self.target_tree.heading("line_id", text="Line ID")
        self.target_tree.heading("product", text="Produit")
        self.target_tree.column("acc_id", width=250)
        self.target_tree.column("line_id", width=320)
        self.target_tree.column("product", width=300)

        # Style sombre pour le Treeview (cohérent avec customtkinter)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Treeview",
            background="#2b2b2b",
            foreground="white",
            fieldbackground="#2b2b2b",
            rowheight=28,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Treeview.Heading",
            background=COLOR_DARK,
            foreground=COLOR_GOLD,
            font=("Segoe UI", 10, "bold"),
        )
        style.map("Treeview", background=[("selected", "#3a3520")])

        # Scrollbar verticale
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.target_tree.yview)
        self.target_tree.configure(yscrollcommand=scrollbar.set)
        self.target_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Double-clic pour éditer une cible
        self.target_tree.bind("<Double-1>", self._edit_target_event)

        # Charger les cibles depuis la configuration
        self._refresh_targets_view()

    def _add_target(self):
        """Ouvre le dialogue d'ajout d'une cible."""
        dialog = TargetDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            targets = self.config.get_targets()
            targets.append(dialog.result)
            self.config.set_targets(targets)
            self.config.save()
            self._refresh_targets_view()

    def _edit_target_event(self, event=None):
        """Gestionnaire du double-clic sur le Treeview."""
        self._edit_target_btn()

    def _edit_target_btn(self):
        """Ouvre le dialogue de modification pour la cible sélectionnée."""
        selection = self.target_tree.selection()
        if not selection:
            return

        idx = self.target_tree.index(selection[0])
        targets = self.config.get_targets()
        if idx >= len(targets):
            return

        dialog = TargetDialog(self, targets[idx])
        self.wait_window(dialog)
        if dialog.result:
            targets[idx] = dialog.result
            self.config.set_targets(targets)
            self.config.save()
            self._refresh_targets_view()

    def _duplicate_target(self):
        """Duplique les cibles sélectionnées."""
        selection = self.target_tree.selection()
        if not selection:
            return

        targets = self.config.get_targets()
        for item in selection:
            idx = self.target_tree.index(item)
            if idx < len(targets):
                original = targets[idx]
                targets.append(Target(
                    acc_id=original.acc_id,
                    line_id=original.line_id,
                    product=original.product,
                ))

        self.config.set_targets(targets)
        self.config.save()
        self._refresh_targets_view()

    def _delete_target(self):
        """Supprime les cibles sélectionnées."""
        selection = self.target_tree.selection()
        if not selection:
            return

        targets = self.config.get_targets()
        # Supprimer en ordre inverse pour préserver les indices
        indices = sorted(
            [self.target_tree.index(item) for item in selection],
            reverse=True,
        )
        for idx in indices:
            if idx < len(targets):
                del targets[idx]

        self.config.set_targets(targets)
        self.config.save()
        self._refresh_targets_view()

    def _clear_targets(self):
        """Supprime toutes les cibles après confirmation."""
        if not self.config.get_targets():
            return
        if messagebox.askyesno("Confirmation", "Supprimer toutes les cibles ?"):
            self.config.set_targets([])
            self.config.save()
            self._refresh_targets_view()

    def _import_urls(self):
        """Ouvre le dialogue d'importation d'URLs."""
        dialog = ImportDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            targets = self.config.get_targets()
            targets.extend(dialog.result)
            self.config.set_targets(targets)
            self.config.save()
            self._refresh_targets_view()

    def _refresh_targets_view(self):
        """Rafraîchit l'affichage du tableau des cibles."""
        self.target_tree.delete(*self.target_tree.get_children())
        targets = self.config.get_targets()
        for t in targets:
            self.target_tree.insert("", "end", values=(t.acc_id, t.line_id, t.product))
        self.target_count_label.configure(text=f"{len(targets)} cible(s)")

    # ========================================
    # Onglet Configuration
    # ========================================

    def _build_config_tab(self):
        """Onglet de configuration des paramètres de l'application."""
        tab = self.tabview.add("Configuration")

        form = ctk.CTkFrame(tab)
        form.pack(fill="x", padx=20, pady=20)

        # Intervalle entre les cycles
        ctk.CTkLabel(
            form, text="Intervalle entre cycles (minutes) :",
            font=ctk.CTkFont(size=13),
        ).grid(row=0, column=0, sticky="w", pady=10, padx=15)
        self.interval_var = ctk.StringVar(value=str(self.config.interval_minutes))
        ctk.CTkEntry(form, textvariable=self.interval_var, width=120).grid(
            row=0, column=1, pady=10, padx=10,
        )

        # Timeout des requêtes
        ctk.CTkLabel(
            form, text="Timeout requêtes HTTP (secondes) :",
            font=ctk.CTkFont(size=13),
        ).grid(row=1, column=0, sticky="w", pady=10, padx=15)
        self.timeout_var = ctk.StringVar(value=str(self.config.timeout_seconds))
        ctk.CTkEntry(form, textvariable=self.timeout_var, width=120).grid(
            row=1, column=1, pady=10, padx=10,
        )

        # Nombre de workers max
        ctk.CTkLabel(
            form, text="Workers max :",
            font=ctk.CTkFont(size=13),
        ).grid(row=2, column=0, sticky="w", pady=10, padx=15)
        self.workers_var = ctk.StringVar(value=str(self.config.max_workers))
        ctk.CTkEntry(form, textvariable=self.workers_var, width=120).grid(
            row=2, column=1, pady=10, padx=10,
        )

        # Nom du profil Firefox
        ctk.CTkLabel(
            form, text="Profil Firefox :",
            font=ctk.CTkFont(size=13),
        ).grid(row=3, column=0, sticky="w", pady=10, padx=15)
        self.profile_var = ctk.StringVar(value=self.config.firefox_profile)
        ctk.CTkEntry(form, textvariable=self.profile_var, width=280).grid(
            row=3, column=1, pady=10, padx=10,
        )

        # Note d'aide
        ctk.CTkLabel(
            form,
            text=(
                "Le profil Firefox doit exister dans ~/.mozilla/firefox/ (Linux) "
                "ou %APPDATA%\\Mozilla\\Firefox\\Profiles\\ (Windows).\n"
                "Créez-le via Firefox : about:profiles"
            ),
            text_color="gray",
            font=ctk.CTkFont(size=11),
            wraplength=500,
            justify="left",
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=15, pady=(5, 15))

        # Bouton sauvegarder
        ctk.CTkButton(
            form, text="Sauvegarder la configuration",
            command=self._save_config, width=200,
        ).grid(row=5, column=0, columnspan=2, pady=15)

    def _save_config(self):
        """Valide et sauvegarde la configuration."""
        try:
            interval = int(self.interval_var.get())
            timeout = int(self.timeout_var.get())
            workers = int(self.workers_var.get())
            profile = self.profile_var.get().strip()

            # Validation des bornes
            if interval < 1:
                raise ValueError("L'intervalle doit être >= 1 minute")
            if timeout < 1:
                raise ValueError("Le timeout doit être >= 1 seconde")
            if workers < 1:
                raise ValueError("Le nombre de workers doit être >= 1")
            if not profile:
                raise ValueError("Le nom du profil Firefox ne peut pas être vide")

            self.config.interval_minutes = interval
            self.config.timeout_seconds = timeout
            self.config.max_workers = workers
            self.config.firefox_profile = profile
            self.config.save()

            messagebox.showinfo("Configuration", "Configuration sauvegardée avec succès.")

        except ValueError as e:
            messagebox.showerror("Erreur de validation", str(e))

    # ========================================
    # Onglet Journal (Logs)
    # ========================================

    def _build_log_tab(self):
        """Onglet d'affichage des logs en temps réel."""
        tab = self.tabview.add("Journal")

        # Barre d'outils
        toolbar = ctk.CTkFrame(tab, fg_color="transparent")
        toolbar.pack(fill="x", padx=5, pady=5)

        ctk.CTkButton(
            toolbar, text="Effacer", command=self._clear_logs, width=80,
        ).pack(side="left", padx=2)

        self.autoscroll_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            toolbar, text="Défilement auto",
            variable=self.autoscroll_var,
        ).pack(side="left", padx=15)

        # Zone de texte pour les logs (lecture seule)
        self.log_text = ctk.CTkTextbox(
            tab, state="disabled",
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)

    def _append_log(self, message: str, level: str = "info"):
        """Ajoute une ligne de log dans le journal avec horodatage."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix_map = {"info": "INFO", "warning": "WARN", "error": "ERR "}
        prefix = prefix_map.get(level, "INFO")
        line = f"[{timestamp}] {prefix} | {message}\n"

        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)

        # Limiter à 5000 lignes pour éviter la surconsommation mémoire
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > 5000:
            self.log_text.delete("1.0", "1001.0")

        if self.autoscroll_var.get():
            self.log_text.see("end")

        self.log_text.configure(state="disabled")

    def _clear_logs(self):
        """Efface le contenu du journal."""
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ========================================
    # Onglet Statistiques
    # ========================================

    def _build_stats_tab(self):
        """Onglet d'affichage des statistiques en temps réel."""
        tab = self.tabview.add("Statistiques")

        self.stats_frame = ctk.CTkFrame(tab)
        self.stats_frame.pack(fill="both", expand=True, padx=20, pady=20)

        self.stat_labels = {}

        # Définition des statistiques affichées
        stats_def = [
            ("cycles", "Cycles complétés"),
            ("total", "Requêtes totales"),
            ("success", "Succès"),
            ("failed", "Échecs"),
            ("rate", "Taux de réussite"),
            ("uptime", "Temps d'activité"),
        ]

        for i, (key, label_text) in enumerate(stats_def):
            ctk.CTkLabel(
                self.stats_frame, text=f"{label_text} :",
                font=ctk.CTkFont(size=15),
            ).grid(row=i, column=0, sticky="w", pady=10, padx=25)

            value_label = ctk.CTkLabel(
                self.stats_frame, text="0",
                font=ctk.CTkFont(size=15, weight="bold"),
            )
            value_label.grid(row=i, column=1, sticky="w", pady=10, padx=25)
            self.stat_labels[key] = value_label

    def _update_stats(self, data: dict):
        """Met à jour les labels de statistiques."""
        for key, label in self.stat_labels.items():
            if key in data:
                label.configure(text=str(data[key]))

    # ========================================
    # Contrôle du moteur
    # ========================================

    def _start_engine(self):
        """Démarre le moteur de traitement."""
        if self.engine and self.engine.is_running:
            return

        # Recharger la configuration depuis le disque
        self.config = AppConfig.load()

        if not self.config.get_targets():
            messagebox.showwarning(
                "Aucune cible",
                "Ajoutez au moins une cible avant de démarrer.",
            )
            return

        self.engine = StarlinkEngine(self.config)
        self.engine.start()

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_label.configure(text="En cours...", text_color=COLOR_GOLD)
        self._append_log("Moteur démarré")

    def _stop_engine(self):
        """Demande l'arrêt du moteur."""
        if self.engine:
            self.engine.stop()
            self._append_log("Arrêt demandé...")

    # ========================================
    # Polling de la queue du moteur
    # ========================================

    def _poll_messages(self):
        """
        Interroge la file de messages du moteur à intervalles réguliers.
        Met à jour la GUI en fonction des messages reçus.
        Appelé toutes les 100ms via after().
        """
        if self.engine:
            try:
                while True:
                    msg_type, data = self.engine.message_queue.get_nowait()

                    if msg_type == MSG_LOG:
                        self._append_log(data["message"], data.get("level", "info"))

                    elif msg_type == MSG_STATUS:
                        self._handle_status_update(data)

                    elif msg_type == MSG_STATS:
                        self._update_stats(data)

                    elif msg_type == MSG_LOGIN_REQUIRED:
                        self._show_login_dialog()

                    elif msg_type == MSG_STOPPED:
                        self.start_btn.configure(state="normal")
                        self.stop_btn.configure(state="disabled")

            except queue.Empty:
                pass

        # Replanifier le prochain polling
        self.after(POLL_INTERVAL_MS, self._poll_messages)

    def _handle_status_update(self, data):
        """Traite les mises à jour de statut du moteur."""
        # Table de correspondance statut -> (texte, couleur)
        status_map = {
            "running": ("En cours...", COLOR_GOLD),
            "waiting": ("En attente du prochain cycle", COLOR_WARNING),
            "stopping": ("Arrêt en cours...", COLOR_DANGER),
            "stopped": ("Arrêté", "gray"),
        }

        if isinstance(data, str) and data.startswith("waiting:"):
            # Afficher le temps restant avant le prochain cycle
            remaining = int(data.split(":")[1])
            minutes = remaining // 60
            seconds = remaining % 60
            self.status_label.configure(
                text=f"Prochain cycle dans {minutes}m{seconds:02d}s",
                text_color=COLOR_WARNING,
            )
        elif data in status_map:
            text, color = status_map[data]
            self.status_label.configure(text=text, text_color=color)

    def _show_login_dialog(self):
        """
        Affiche un dialogue demandant à l'utilisateur de se connecter dans Firefox.
        Bloque la GUI jusqu'à ce que l'utilisateur clique OK.
        """
        messagebox.showinfo(
            "Connexion requise",
            "Connectez-vous dans la fenêtre Firefox qui s'est ouverte,\n"
            "puis cliquez OK une fois connecté à votre compte Starlink.",
        )
        # Confirmer au moteur que le login est fait
        if self.engine:
            self.engine.confirm_login()

    # ========================================
    # Fermeture propre
    # ========================================

    def _show_about(self):
        """Affiche le dialogue A propos avec les infos Saadaw Systems."""
        about_window = ctk.CTkToplevel(self)
        about_window.title(f"A propos - {__app_name__}")
        about_window.geometry("420x380")
        about_window.resizable(False, False)

        # Logo centré
        if self._header_logo:
            # Image plus grande pour le dialogue
            try:
                icon_path = get_asset_path("icon.png")
                pil_image = Image.open(icon_path)
                about_logo = ctk.CTkImage(
                    light_image=pil_image, dark_image=pil_image,
                    size=(80, 80),
                )
                ctk.CTkLabel(about_window, image=about_logo, text="").pack(pady=(20, 10))
            except Exception:
                pass

        # Nom de l'application
        ctk.CTkLabel(
            about_window, text=__app_name__,
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack()

        ctk.CTkLabel(
            about_window, text=f"Version {__version__}",
            text_color="gray",
        ).pack(pady=(2, 15))

        # Separateur visuel (ligne or)
        ctk.CTkFrame(
            about_window, height=2, fg_color=COLOR_GOLD,
        ).pack(fill="x", padx=40, pady=5)

        # Infos entreprise
        ctk.CTkLabel(
            about_window, text=__company__,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLOR_GOLD,
        ).pack(pady=(15, 2))

        ctk.CTkLabel(
            about_window, text=__company_slogan__,
            font=ctk.CTkFont(size=12),
            text_color=COLOR_GOLD_DARK,
        ).pack()

        # Coordonnees (site et email cliquables)
        info_frame = ctk.CTkFrame(about_window, fg_color="transparent")
        info_frame.pack(pady=15)

        # Infos avec liens cliquables pour site et email
        info_rows = [
            ("Site", __company_url__, __company_url__),
            ("Email", __company_email__, f"mailto:{__company_email__}"),
            ("Tel", "+227 89 86 80 81", None),
            ("Lieu", "Niamey, Niger", None),
        ]

        for label_text, display_text, url in info_rows:
            row = ctk.CTkFrame(info_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(
                row, text=f"{label_text} :", width=50,
                font=ctk.CTkFont(size=11), text_color="gray",
                anchor="e",
            ).pack(side="left", padx=(0, 8))

            if url:
                # Label cliquable : texte or, curseur main, ouvre dans le navigateur
                link = ctk.CTkLabel(
                    row, text=display_text,
                    font=ctk.CTkFont(size=11),
                    text_color=COLOR_GOLD, cursor="hand2", anchor="w",
                )
                link.pack(side="left")
                link.bind("<Button-1>", lambda e, u=url: _open_url(u))
                link.bind("<Enter>", lambda e, w=link: w.configure(
                    font=ctk.CTkFont(size=11, underline=True)))
                link.bind("<Leave>", lambda e, w=link: w.configure(
                    font=ctk.CTkFont(size=11, underline=False)))
            else:
                ctk.CTkLabel(
                    row, text=display_text, font=ctk.CTkFont(size=11),
                    anchor="w",
                ).pack(side="left")

        # Bouton Fermer
        ctk.CTkButton(
            about_window, text="Fermer", command=about_window.destroy,
            fg_color=COLOR_GOLD, hover_color=COLOR_GOLD_HOVER,
            text_color=COLOR_DARK, width=100,
        ).pack(pady=(10, 15))

        # Modale : transient + grab différé (fix fenêtre vide sur Linux)
        about_window.transient(self)
        about_window.after(150, lambda: (
            about_window.lift(),
            about_window.focus_force(),
            about_window.grab_set(),
        ))

    # ========================================
    # Fermeture propre
    # ========================================

    def _on_close(self):
        """Gère la fermeture propre de l'application."""
        if self.engine and self.engine.is_running:
            if not messagebox.askyesno(
                "Quitter",
                "Le moteur est en cours d'exécution.\nVoulez-vous vraiment quitter ?",
            ):
                return
            self.engine.stop()

        self.destroy()
