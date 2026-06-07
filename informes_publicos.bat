@echo off
REM ============================================================
REM   Informes de seguimiento por publico (Mailchimp -> Excel)
REM   Doble clic y sigue las instrucciones.
REM ============================================================
cd /d "%~dp0"

echo Instalando lo necesario (solo la primera vez)...
py -m pip install --quiet requests openpyxl

echo.
set /p MCKEY=Pega aqui tu clave de Mailchimp y pulsa Enter:

echo.
echo Sacando los datos de marzo y abril 2026 de los 7 publicos...
py extraer_datos_publicos.py --api-key %MCKEY% --desde 2026-03-01 --hasta 2026-04-30

echo.
echo Listo. Los Excel estan en la carpeta "informes".
start "" "%~dp0informes"
pause
