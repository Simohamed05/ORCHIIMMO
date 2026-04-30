@echo off
title Orchiimmo — Serveur Django (Maroc MAD)
color 0A

echo.
echo  ============================================
echo   ORCHIIMMO — Plateforme Immobiliere Maroc
echo   Phase 2 Django ^| Prix en MAD
echo  ============================================
echo.

:: Aller dans le bon dossier
cd /d "%~dp0"

:: Activer le venv si present
if exist "venv\Scripts\activate.bat" (
    echo [1/4] Activation de l'environnement virtuel...
    call venv\Scripts\activate.bat
) else (
    echo [!] Venv non trouve — utilisation de Python global
)

:: Verifier les migrations
echo [2/4] Application des migrations...
python manage.py migrate --run-syncdb

:: Collecter les fichiers statiques (optionnel en dev)
:: python manage.py collectstatic --noinput

:: Lancer le serveur
echo [3/4] Demarrage du serveur Django...
echo.
echo  Acces : http://localhost:8000
echo  Admin : http://localhost:8000/admin/
echo.
echo  Commandes utiles (dans un autre terminal) :
echo    python manage.py import_csv          -- Importer les donnees
echo    python ml\train.py                   -- Entrainer le modele ML
echo    python manage.py createsuperuser     -- Creer un admin
echo.
echo  Appuyez sur Ctrl+C pour arreter le serveur
echo  ============================================
echo.

python manage.py runserver 0.0.0.0:8000

pause
