@echo off
REM ============================================================
REM   Informe Excel (formato OPERINTER) para el publico OPZGZ
REM   Doble clic y sigue las instrucciones.
REM ============================================================
cd /d "%~dp0"

echo Instalando lo necesario (solo la primera vez)...
py -m pip install --quiet requests openpyxl

echo.
set /p MCKEY=Pega aqui tu clave de Mailchimp y pulsa Enter:

echo.
echo Periodo del informe. Pulsa Enter para usar enero-febrero 2026,
echo o escribe otras fechas en formato AAAA-MM-DD.
set DESDE=2026-01-01
set HASTA=2026-02-28
set /p DESDE=  Desde [2026-01-01]:
set /p HASTA=  Hasta [2026-02-28]:

echo.
echo Generando informe de OPZGZ de %DESDE% a %HASTA%...
py informe_estilo_excel.py --audience OPZGZ --desde %DESDE% --hasta %HASTA% --api-key %MCKEY%

echo.
echo Listo. El Excel esta en esta misma carpeta.
start "" "%~dp0"
pause
