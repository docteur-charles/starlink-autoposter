# -*- mode: python ; coding: utf-8 -*-
"""
Spec PyInstaller pour Starlink AutoPoster.
Génère un exécutable autonome (.exe sous Windows, binaire sous Linux).
Embarque customtkinter et toutes les dépendances nécessaires.
"""

import os
import sys

# Detecter la racine du projet (fonctionne que le build soit lance depuis
# la racine ou depuis le dossier packaging/)
SPEC_DIR = os.path.dirname(os.path.abspath(SPECPATH)) if 'SPECPATH' in dir() else os.path.dirname(os.path.abspath(__file__))
if os.path.basename(SPEC_DIR) == 'packaging':
    PROJECT_ROOT = os.path.dirname(SPEC_DIR)
else:
    PROJECT_ROOT = SPEC_DIR

# Localiser customtkinter pour inclure ses themes/assets
import customtkinter
ctk_path = os.path.dirname(customtkinter.__file__)

block_cipher = None

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'starlink_autoposter', '__main__.py')],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[
        # Inclure les assets de customtkinter (themes, polices, etc.)
        (ctk_path, 'customtkinter/'),
        # Inclure les assets de l'application (logo Saadaw Systems, icones)
        (os.path.join(PROJECT_ROOT, 'starlink_autoposter', 'assets'), 'starlink_autoposter/assets/'),
    ],
    hiddenimports=[
        'customtkinter',
        'PIL',
        'PIL._tkinter_finder',
        'requests',
        'urllib3',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclure les modules inutiles pour réduire la taille
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='starlink-autoposter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # console=False pour Windows (pas de fenêtre console)
    # console=True pour Linux (utile pour le debug)
    console=sys.platform != 'win32',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
