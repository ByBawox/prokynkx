@echo off
chcp 65001 > nul
title ByNahro FULL IPTV - Ülke Menüsü
color 0a

echo.
echo =====================================================
echo     ByNahro RESOLVER - TÜM ÜLKELER + ÜLKE MENÜSÜ
echo =====================================================
echo.

:menu
echo 1. Tek kanal linki al (örnek: Rai 1)
echo 2. TÜM ÜLKELERİ çek ve NahroTo_full.m3u oluştur
echo 3. BELİRLİ ÜLKE seç ve M3U oluştur (MENÜDEN SEÇ)
echo 4. Çıkış
echo.
set /p secim=Seçiminizi yapın (1-4): 

if "%secim%"=="1" goto tek
if "%secim%"=="2" goto full
if "%secim%"=="3" goto ulke_menu
if "%secim%"=="4" goto cik
echo Yanlış seçim!
goto menu

:tek
set /p kanal=Kanali girin (örnek: Rai 1): 
echo.
echo [ÇALIŞIYOR] %kanal% için link alınıyor...
py vavoo_resolver.py "%kanal%" --vavoo-iptv
echo.
pause
goto menu

:full
echo.
echo TÜM ÜLKELERDEN KANALLAR ÇEKİLİYOR...
py vavoo_resolver.py --full-m3u
echo.
pause
goto menu

:ulke_menu
echo.
echo ÜLKE SEÇİN (numara girin):
echo 1. Turkey
echo 2. Germany
echo 3. Balkans
echo 4. Bulgaria
echo 5. France
echo 6. Arabia
echo 7. Italy
echo 8. Netherlands
echo 9. Poland
echo 10. Portugal
echo 11. Romania
echo 12. Russia
echo 13. Spain
echo 14. Albania
echo 15. United Kingdom
echo 16. United States
echo.
set /p ulke_secim=Seçiminizi yapın (1-16): 

if "%ulke_secim%"=="1" set ulke=Turkey
if "%ulke_secim%"=="2" set ulke=Germany
if "%ulke_secim%"=="3" set ulke=Balkans
if "%ulke_secim%"=="4" set ulke=Bulgaria
if "%ulke_secim%"=="5" set ulke=France
if "%ulke_secim%"=="6" set ulke=Arabia
if "%ulke_secim%"=="7" set ulke=Italy
if "%ulke_secim%"=="8" set ulke=Netherlands
if "%ulke_secim%"=="9" set ulke=Poland
if "%ulke_secim%"=="10" set ulke=Portugal
if "%ulke_secim%"=="11" set ulke=Romania
if "%ulke_secim%"=="12" set ulke=Russia
if "%ulke_secim%"=="13" set ulke=Spain
if "%ulke_secim%"=="14" set ulke=Albania
if "%ulke_secim%"=="15" set ulke="United Kingdom"
if "%ulke_secim%"=="16" set ulke="United States"

if not defined ulke (
    echo Yanlış seçim!
    pause
    goto ulke_menu
)

echo.
echo [ÇALIŞIYOR] %ulke% için M3U oluşturuluyor...
py vavoo_resolver.py --country-m3u "%ulke%"
echo.
pause
goto menu

:cik
echo Güle güle!
pause