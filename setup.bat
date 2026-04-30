@echo off
title Orchiimmo — Installation Initiale
color 0B

echo.
echo  ============================================
echo   ORCHIIMMO — Installation Phase 2
echo   A executer UNE SEULE FOIS
echo  ============================================
echo.

cd /d "%~dp0"

:: 1. Creer le venv
echo [1/7] Creation de l'environnement virtuel Python...
python -m venv venv
if errorlevel 1 (
    echo ERREUR : Python non trouve. Installez Python 3.10+
    pause
    exit /b 1
)

:: 2. Activer le venv
echo [2/7] Activation du venv...
call venv\Scripts\activate.bat

:: 3. Mettre a jour pip
echo [3/7] Mise a jour de pip...
python -m pip install --upgrade pip

:: 4. Installer les dependances
echo [4/7] Installation des dependances (peut prendre 2-5 min)...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERREUR lors de l'installation des packages.
    pause
    exit /b 1
)

:: 5. Creer le fichier .env si absent
if not exist ".env" (
    echo [5/7] Creation du fichier .env...
    copy .env.example .env
    echo      Pensez a modifier SECRET_KEY dans .env !
) else (
    echo [5/7] Fichier .env deja present — OK
)

:: 6. Migrations
echo [6/7] Creation de la base de donnees...
python manage.py makemigrations accounts predictions properties dashboards
python manage.py migrate

:: 7. Superuser
echo [7/7] Voulez-vous creer un superutilisateur admin ? (O/N)
set /p choice=Reponse :
if /i "%choice%"=="O" (
    python manage.py createsuperuser
)

echo.
echo  ============================================
echo   Installation terminee !
echo.
echo   Prochaines etapes :
echo     1. Importez les donnees :
echo        python manage.py import_csv
echo.
echo     2. Entrainezle modele ML :
echo        python ml\train.py
echo.
echo     3. Lancez le serveur :
echo        start.bat
echo  ============================================
echo.
pause
