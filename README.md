# League Mastery Tracker

League Mastery Tracker er en lokal Windows-applikasjon for registrering av personer, Riot-kontoer og League of Legends Champion Mastery.

Applikasjonen kjører en lokal Flask-server og åpner brukergrensesnittet i standardnettleseren. Den ferdige Windows-utgaven kan startes med dobbeltklikk og krever ikke at sluttbrukeren installerer Python, PowerShell-verktøy eller databaseprogrammer.

## Produktidentitet

Gjeldende produktidentitet:

```text
Product name: League Mastery Tracker
Release name: League Mastery Tracker 2.0
Application version: 2.0.0
Windows executable: LeagueMasteryTracker.exe
```

Den autoritative runtime-kilden er `application.config.Config`, med feltene:

```text
Config.PRODUCT_NAME
Config.RELEASE_NAME
Config.APPLICATION_VERSION
Config.WINDOWS_EXECUTABLE_NAME
```

## Gjeldende status

Ferdige hovedsteg:

* Personer og Riot-kontoer
* Champion Mastery-synkronisering
* Lokal SQLite-database
* Databasebackup og kontrollert restore
* Portabel JSON-eksport og -import
* Kryptert lokal lagring av Riot API-nøkkel
* Konsollfri Windows onefile-build
* Én-instanskontroll og kontrollert avslutning
* Medfølgende championdatabase og lokale championikoner
* Offline førstegangsoppstart
* Kontrollert manuell Data Dragon-oppdatering

Automatisert testsuite:

```text
630 tester
```

## Offline championdata

Programmet leveres med et komplett lokalt championdatasett under:

```text
application/
└── bundled_reference_data/
    └── data_dragon/
        ├── manifest.json
        ├── champions.json
        └── champion_icons/
```

Det medfølgende datasettet inneholder:

```text
173 champions
173 lokale championikoner
Locale: en_US
```

En ny installasjon kan derfor vise championnavn og championikoner uten:

* internettilkobling
* Riot API-nøkkel
* tilgjengelig Data Dragon-tjeneste
* manuell registrering av champions

Vanlig oppstart og navigasjon utfører ikke Data Dragon-kall.

## Referansedatakilder

Applikasjonen prioriterer championreferansedata slik:

1. En gyldig lokal Data Dragon-cache dersom den er nyere enn det medfølgende datasettet.
2. Det medfølgende championdatasettet.
3. Eksisterende championposter i SQLite-databasen dersom begge filkildene er utilgjengelige.

Eksisterende champions og mastery-data slettes ikke fordi en champion mangler fra et datasett.

Ukjente Riot champion-ID-er bevares og kan få metadata senere dersom ID-en blir tilgjengelig i et gyldig datasett.

Manuelt registrert championmetadata bevares.

## Data Dragon-oppdatering

Data Dragon brukes bare gjennom en eksplisitt brukerhandling.

En manuell oppdatering:

1. Henter nyeste Data Dragon-versjon.
2. Laster ned championdata og championikoner.
3. Bygger et komplett midlertidig datasett.
4. Validerer manifest, checksum, poster og bilder.
5. Merger metadata transaksjonelt mot databasen.
6. Installerer lokal cache atomisk.
7. Bevarer tidligere fungerende data dersom noe feiler.

En mislykket oppdatering skal ikke gjøre det medfølgende datasettet, gammel cache, database eller mastery-data utilgjengelig.

## Bygge bundled championdatasett

Utviklingsmiljøet må være aktivert og prosjektmappen må være gjeldende arbeidsmappe.

Kjør:

```powershell
python build_champion_reference_bundle.py
```

Kommandoen genererer:

```text
application\bundled_reference_data\data_dragon\manifest.json
application\bundled_reference_data\data_dragon\champions.json
application\bundled_reference_data\data_dragon\champion_icons\
```

Kontroller ressursene:

```powershell
Get-ChildItem `
    application\bundled_reference_data\data_dragon

(Get-ChildItem `
    application\bundled_reference_data\data_dragon\champion_icons `
    -File).Count
```

## Kjøre automatiserte tester

Aktiver prosjektets virtuelle miljø og kjør:

```powershell
python -m unittest discover -s tests -v
```

Forventet gjeldende resultat:

```text
Ran 630 tests
OK
```

## Kjøre fra kildekode

Fra prosjektmappen:

```powershell
python run.py
```

Normal utviklingskjøring krever Python og prosjektets installerte utviklingsavhengigheter.

Dette gjelder ikke den ferdige Windows-programfilen.

## Bygge Windows-programmet

### Konsollfri onefile-utgave

```powershell
Remove-Item `
    build\LeagueMasteryTracker-onefile `
    -Recurse `
    -Force `
    -ErrorAction SilentlyContinue

Remove-Item `
    dist\LeagueMasteryTracker.exe `
    -Force `
    -ErrorAction SilentlyContinue

python -m PyInstaller `
    --clean `
    --noconfirm `
    LeagueMasteryTracker-onefile.spec
```

Ferdig programfil:

```text
dist\LeagueMasteryTracker.exe
```

### PyInstaller-ressurser

Begge spec-filene inkluderer:

* Flask-templates
* statiske filer
* bundled manifest
* bundled championdata
* alle lokale championikoner
* nødvendige `pystray`-moduler

Spec-filer:

```text
LeagueMasteryTracker.spec
LeagueMasteryTracker-onefile.spec
```

Begge spec-filene bruker `pyinstaller_build_metadata.py`. Navnet på programfilen og Windows-versjonsmetadata utledes fra de kanoniske Config-feltene som er oppført under produktidentitet.

Begge spec-filene bruker den samme single-executable-arkitekturen uten en `COLLECT`-fase. På Windows produserer begge `LeagueMasteryTracker.exe`, og dokumentert standardoutput er fortsatt:

```text
dist\LeagueMasteryTracker.exe
```

Windows-versjonsmetadata er implementert i kildekoden og dekket av automatiserte tester. Endelig Windows-aksept gjenstår og krever:

* en ren Windows-build
* verifisering av programfilnavnet
* kontroll under Explorer → Properties → Details

## Windows-oppstart

Den ferdige `.exe`-filen:

* åpner ingen konsoll
* starter den lokale serveren
* åpner standardnettleseren
* hindrer flere samtidige appinstanser
* støtter kontrollert avslutning fra Innstillinger
* kan avsluttes når siste relevante nettleserfane lukkes
* bruker data under den innloggede Windows-brukerens lokale dataområde

## Lokal datamappe

Mutable brukerdata lagres normalt under:

```text
%LOCALAPPDATA%\LeagueMasteryTracker\
```

Dette inkluderer blant annet:

```text
database\
configuration\
reference\
backups\
```

Programfilene og brukerens mutable data holdes adskilt.

Bundled championdata ligger i programmet, mens en senere Data Dragon-cache lagres under brukerens lokale dataområde.

## Riot API-nøkkel

En Riot API-nøkkel kan registreres fra Innstillinger.

Lokalt lagrede nøkler:

* krypteres med Windows DPAPI
* er knyttet til samme Windows-bruker og maskin
* lagres ikke i SQLite-databasen
* inkluderes ikke i databasebackups
* inkluderes ikke i JSON-eksporter
* skal ikke committes til Git

Development API keys fra Riot utløper regelmessig og må erstattes når Riot deaktiverer dem.

## Backup og restore

Databasebackup og JSON-eksport har forskjellige formål.

### Databasebackup

Databasebackup er en full intern SQLite-kopi og brukes til kontrollert restore av den lokale installasjonen.

Applikasjonen:

* kan opprette backup manuelt
* oppretter periodisk startup-backup
* beholder de nyeste backupfilene
* validerer restore-kandidater
* oppretter safety backup før restore
* gjennomfører pending restore under neste oppstart

### JSON-eksport og import

JSON-formatet er en portabel domenedatakontrakt.

Det bruker:

* PUUID som stabil Riot-kontoidentitet
* Riot champion-ID som stabil championidentitet
* nesting for person–konto-relasjoner
* eksplisitt formatversjon
* eksplisitt databaseskjemaversjon

Interne database-ID-er og lokale hemmeligheter eksporteres ikke.

## Isolert offline-test

Den konsollfrie onefile-utgaven er verifisert fra en separat programmappe med en tom, isolert brukerdatamappe og uten internettilkobling.

Følgende er kontrollert:

* normal dobbeltklikkoppstart
* ingen konsoll
* automatisk nettleseråpning
* tom database blir initialisert
* 173 championposter blir tilgjengelige
* championnavn vises offline
* lokale championikoner er tilgjengelige
* ingen manuell Data Dragon-oppdatering er nødvendig
* prosjektmappen brukes ikke som brukerdataområde
* Innstillinger og kontrollert avslutning fungerer

## Juridisk informasjon

League Mastery Tracker isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc.

Programmet bruker championdata og championikoner fra Riot Games Data Dragon. Dataene lagres lokalt for å støtte offline bruk.

Gjeldende Riot-policy og Data Dragon-dokumentasjon er lenket fra Innstillinger i applikasjonen.

## Neste hovedsteg

Neste planlagte hovedsteg er:

```text
Steg 10 – Visuell ferdigstilling og dashboardpolering
```

Dette omfatter blant annet:

* samlet visuell struktur
* forbedret dashboard
* tydeligere navigasjon
* lokal visning av championikoner
* responsiv layout
* bedre presentasjon av personer, kontoer og mastery-data
