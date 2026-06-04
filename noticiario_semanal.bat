@echo off
REM === Noticiario semanal -> borrador en Mailchimp ===
REM Rellena tus dos claves aqui (o dejalas como variables de entorno del sistema).
if "%ANTHROPIC_API_KEY%"=="" set ANTHROPIC_API_KEY=PON_AQUI_TU_CLAVE_ANTHROPIC
if "%MAILCHIMP_API_KEY%"=="" set MAILCHIMP_API_KEY=PON_AQUI_TU_CLAVE_MAILCHIMP

cd /d "%~dp0"

REM Aprende el estilo solo si aun no existe la guia
if not exist estilo_noticiario.json (
    echo Aprendiendo el estilo del noticiario desde el PDF...
    py aprende_estilo.py --pdf viernes_OPZGZ.pdf
)

echo Generando el noticiario de la semana y creando borrador en Mailchimp...
py genera_noticiario.py --audience OPZGZ

echo.
echo Listo. Revisa el borrador en Mailchimp.
pause
