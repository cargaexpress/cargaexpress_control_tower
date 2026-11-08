@echo off
set "PATH=%PATH%;C:\Program Files\Amazon\SessionManagerPlugin\bin"
title CargaExpress RDS Secure Tunnel (Port 5453)
cls
echo ======================================================================
echo   AWS SSM SECURE TUNNEL - POSTGRESQL RDS STAGING CARGAEXPRESS
echo   Local Connection: localhost:5453 ^--> Private AWS RDS: 5432
echo ======================================================================
echo.
echo [1/2] Starting port forwarding session via AWS SSM on port 5453...
echo [2/2] KEEP THIS WINDOW OPEN WHILE USING POWER BI OR LOCAL CLIENTS.
echo.
echo Press Ctrl+C at any time to close the tunnel.
echo ======================================================================
echo.

aws ssm start-session ^
  --target i-004830098afc09efb ^
  --document-name AWS-StartPortForwardingSessionToRemoteHost ^
  --parameters file://ssm_port_forward.json ^
  --region us-east-2

pause
