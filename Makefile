# ============================================================
# Makefile pour Starlink AutoPoster
# Commandes de build et d'exécution de l'application
# ============================================================

.PHONY: install run exe deb clean help

# Installer les dépendances Python
install:
	pip install -r requirements.txt

# Lancer l'application en mode développement
run:
	python -m starlink_autoposter

# Construire l'exécutable autonome (Linux ou Windows selon l'OS)
exe:
	pip install pyinstaller
	pyinstaller packaging/starlink-autoposter.spec \
		--distpath build/dist \
		--workpath build/work \
		--clean -y

# Construire le paquet .deb (Linux uniquement)
deb:
	bash packaging/build_deb.sh

# Nettoyer les fichiers de build
clean:
	rm -rf build/ dist/

# Afficher l'aide
help:
	@echo "Commandes disponibles :"
	@echo "  make install  - Installer les dépendances Python"
	@echo "  make run      - Lancer l'application"
	@echo "  make exe      - Construire l'exécutable autonome"
	@echo "  make deb      - Construire le paquet .deb (Linux)"
	@echo "  make clean    - Nettoyer les fichiers de build"
