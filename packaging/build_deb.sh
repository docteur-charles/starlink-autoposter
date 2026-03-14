#!/bin/bash
# ==============================================================
# Script de construction du paquet .deb pour Starlink AutoPoster
# Utilise PyInstaller pour créer un binaire autonome,
# puis l'emballe dans un paquet Debian (.deb).
# ==============================================================

set -e

VERSION="1.0.0"
PKG_NAME="starlink-autoposter"
ARCH=$(dpkg --print-architecture)

# Répertoires de travail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="${PROJECT_DIR}/build"
DIST_DIR="${BUILD_DIR}/dist"
DEB_ROOT="${BUILD_DIR}/deb/${PKG_NAME}_${VERSION}_${ARCH}"

echo "=== Construction du paquet .deb ==="
echo "Version     : ${VERSION}"
echo "Architecture : ${ARCH}"
echo "Projet      : ${PROJECT_DIR}"
echo ""

# 1. Créer un venv de build et installer les dépendances
VENV_DIR="${BUILD_DIR}/venv"
echo ">>> Création du venv de build..."
python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

echo ">>> Installation des dépendances de build..."
pip install --quiet pyinstaller
pip install --quiet -r "${PROJECT_DIR}/requirements.txt"

# 2. Construire le binaire avec PyInstaller
echo ">>> Compilation du binaire avec PyInstaller..."
cd "${PROJECT_DIR}"
pyinstaller \
    "packaging/starlink-autoposter.spec" \
    --distpath "${DIST_DIR}" \
    --workpath "${BUILD_DIR}/work" \
    --clean \
    -y

# Vérifier que le binaire existe
if [ ! -f "${DIST_DIR}/starlink-autoposter" ]; then
    echo "ERREUR : Le binaire n'a pas été généré."
    exit 1
fi

echo ">>> Binaire créé : $(du -h "${DIST_DIR}/starlink-autoposter" | cut -f1)"

# 3. Créer la structure du paquet .deb
echo ">>> Construction de la structure .deb..."
rm -rf "${DEB_ROOT}"
mkdir -p "${DEB_ROOT}/DEBIAN"
mkdir -p "${DEB_ROOT}/usr/bin"
mkdir -p "${DEB_ROOT}/usr/share/applications"
mkdir -p "${DEB_ROOT}/usr/share/doc/${PKG_NAME}"
mkdir -p "${DEB_ROOT}/etc/xdg/autostart"

# 4. Copier le binaire
cp "${DIST_DIR}/starlink-autoposter" "${DEB_ROOT}/usr/bin/"
chmod 755 "${DEB_ROOT}/usr/bin/starlink-autoposter"

# 5. Copier le fichier .desktop (menu + autostart au démarrage)
cp "${SCRIPT_DIR}/starlink-autoposter.desktop" "${DEB_ROOT}/usr/share/applications/"
cp "${SCRIPT_DIR}/starlink-autoposter.desktop" "${DEB_ROOT}/etc/xdg/autostart/"

# 6. Fichier de contrôle Debian
cat > "${DEB_ROOT}/DEBIAN/control" << EOF
Package: ${PKG_NAME}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Depends: firefox | firefox-esr
Installed-Size: $(du -sk "${DEB_ROOT}/usr" | cut -f1)
Maintainer: Saadaw Systems <contact@saadaw-systems.org>
Homepage: https://saadaw-systems.org
Description: Gestion automatique des abonnements Starlink - Saadaw Systems
 Application graphique pour automatiser les changements d'abonnement
 sur les comptes Starlink. Utilise Firefox pour l'authentification.
 .
 Developpee par Saadaw Systems - Architectes du Numerique
 .
 Fonctionnalites :
  - Gestion multi-comptes
  - Changement automatique de forfait
  - Interface graphique moderne
  - Execution cyclique configurable
EOF

# 7. Script post-installation (créer le répertoire de config)
cat > "${DEB_ROOT}/DEBIAN/postinst" << 'EOF'
#!/bin/bash
echo "Starlink AutoPoster installé avec succès."
echo "Lancez l'application depuis le menu ou tapez : starlink-autoposter"
EOF
chmod 755 "${DEB_ROOT}/DEBIAN/postinst"

# 8. Fichier copyright
cat > "${DEB_ROOT}/usr/share/doc/${PKG_NAME}/copyright" << EOF
Starlink AutoPoster v${VERSION}
Saadaw Systems - Architectes du Numerique
https://saadaw-systems.org | contact@saadaw-systems.org
Usage personnel uniquement.
EOF

# 9. Construire le .deb
echo ">>> Assemblage du paquet .deb..."
dpkg-deb --build --root-owner-group "${DEB_ROOT}"

DEB_FILE="${DEB_ROOT}.deb"

if [ -f "${DEB_FILE}" ]; then
    echo ""
    echo "=== Paquet créé avec succès ==="
    echo "Fichier : ${DEB_FILE}"
    echo "Taille  : $(du -h "${DEB_FILE}" | cut -f1)"
    echo ""
    echo "Installation : sudo dpkg -i ${DEB_FILE}"
    echo "Désinstallation : sudo apt remove ${PKG_NAME}"
else
    echo "ERREUR : Le paquet .deb n'a pas été créé."
    exit 1
fi
