"""
Setup de l'application Starlink AutoPoster.
Permet l'installation via pip et la création de l'exécutable.
"""

from setuptools import setup, find_packages

setup(
    name="starlink-autoposter",
    version="1.0.0",
    description="Application de gestion automatique des abonnements Starlink",
    author="Saadaw Systems",
    author_email="contact@saadaw-systems.org",
    url="https://saadaw-systems.org",
    packages=find_packages(),
    package_data={
        "starlink_autoposter": ["assets/*.png", "assets/*.svg"],
    },
    install_requires=[
        "customtkinter>=5.2.0",
        "requests>=2.31.0",
        "selenium>=4.15.0",
        "urllib3>=2.0.0",
        "Pillow>=10.0.0",
    ],
    entry_points={
        "gui_scripts": [
            "starlink-autoposter=starlink_autoposter.__main__:main",
        ],
    },
    python_requires=">=3.9",
)
