# protokollet

*§1: mötets öppnande — klicka Start. En mötesinspelare för Windows som spelar in, transkriberar och skriver protokollet åt dig.*

*Read this in [English](README.en.md).*

**Version:** 1.6.0
**Författare:** Jan Soja
**Skapad:** 2026-03-26

protokollet är ett litet Windows-program som bor i systemfältet.
Du klickar på **Start** när mötet börjar och **Stop** när det slutar — det
spelar in både din mikrofon och övriga deltagare, transkriberar samtalet
och sparar prydliga mötesanteckningar (sammanfattning, beslut och
åtgärdspunkter) som en textfil du kan läsa i valfri editor.

Det är byggt för svenska möten (med en svenskoptimerad taligenkänningsmodell)
men fungerar även för andra språk. Ingen GPU eller speciell hårdvara behövs.

> **Om integritet:** Ditt ljud skickas till tjänsten
> [berget.ai](https://berget.ai) för transkribering och sammanfattning.
> Inget laddas upp någon annanstans, och inspelningarna stannar på din
> dator. Använd bara programmet för möten du får spela in — kolla vilka
> regler som gäller och berätta för deltagarna.

---

## Kom igång

Steg 1–3 gör du bara en gång. Sedan är inspelning bara steg 4.

### 1. Installera Python (engångsgrej)

Ladda ner och installera Python 3.10 eller nyare från
**[python.org/downloads](https://www.python.org/downloads/)**.

> ⚠️ På installationsprogrammets första skärm: bocka i rutan
> **"Add python.exe to PATH"** innan du klickar på Install. Den lilla
> kryssrutan är det som får resten av installationen att fungera
> automatiskt.

### 2. Ladda ner protokollet

På GitHub-sidan: klicka på den gröna **Code**-knappen → **Download ZIP**.
Högerklicka sedan på den nedladdade filen → **Extrahera alla** till en mapp
du kommer ihåg (t.ex. `Dokument\protokollet`).

*(Kan du Git går `git clone` lika bra — samma resultat.)*

### 3. Kör installationen

Dubbelklicka på **`setup.bat`** i mappen. Ett fönster öppnas och guidar
dig genom allt:

- kontrollerar att Python är installerat
- installerar komponenterna programmet behöver
- ber dig klistra in din **API-nyckel från berget.ai**

En gratis API-nyckel får du genom att registrera dig på
**[berget.ai](https://berget.ai)**. Kopiera nyckeln, klistra in den i
installationsfönstret när du blir tillfrågad och tryck Enter.

När det står *"Setup complete!"* är du klar.

### 4. Spela in ett möte

1. Dubbelklicka på **`Recorder.bat`**. En rund ikon dyker upp i
   systemfältet (nere till höger på skärmen, vid klockan).
2. **Högerklicka på ikonen → Start Recording** när mötet börjar.
3. **Högerklicka på ikonen → Stop Recording** när det slutar.
4. Efter en kort transkribering visas en avisering och dina anteckningar
   sparas i `Dokument\Recordings` (din användarmapp) som en `.md`-fil —
   till exempel `2026-04-01_14-31_budgetplanering-q3.md`.

---

## Skärmbilder

> 📷 _Det här är platshållare. Ta bilderna på din egen dator, spara dem i
> en `docs/`-mapp och avkommentera motsvarande rad nedan._

<!-- ![Ikonen i systemfältet och högerklicksmenyn](docs/tray-menu.png) -->
<!-- ![Inspelningspanelen under inspelning](docs/recording-pill.png) -->
<!-- ![Exempel på färdiga mötesanteckningar](docs/example-notes.png) -->

Förslag på bilder: (1) menyn i systemfältet öppen, (2) inspelningspanelen
under inspelning, (3) en färdig `.md`-fil öppnad i en editor.

---

## Så fungerar det

1. **Start** — Högerklicka på ikonen i systemfältet och välj
   "Start Recording".
2. **Inspelning** — Två separata ljudströmmar fångas:
   - **Mikrofonen** (din röst)
   - **Systemets loopback** (övriga deltagare, via WASAPI)
3. **Stopp** — Klicka på "Stop Recording" när mötet är slut.
4. **Transkribering** — Varje ström skickas till berget.ai:s API
   (kb-whisper-large) för transkribering. Mikrofonljudet märks med ditt
   namn (konfigurerbart), loopback märks "Others".
5. **LLM-sammanfattning** — Råtranskriptet bearbetas av Mistral till
   strukturerade mötesanteckningar.
6. **Resultat** — En beskrivande namngiven markdown-fil (t.ex.
   `2026-04-01_14-31_budgetplanering-q3.md`) med:

   ```markdown
   # Mötesprotokoll 2026-03-26 14:30

   ## Sammanfattning
   Kort sammanfattning av mötet...

   ## Beslut
   - Viktiga beslut som fattades

   ## Åtgärdspunkter
   - Åtgärder med ansvariga

   ## Mötesanteckningar
   Renskriven prosaversion av samtalet...

   ---

   ## Rå transkribering
   Jan: ursprunglig transkriberad text...
   Others: ursprunglig transkriberad text...
   ```

### Systemfältet

| Ikonfärg | Betydelse                                      |
| -------- | ---------------------------------------------- |
| Grå      | Redo                                           |
| Röd      | Spelar in                                      |
| Blå      | Transkriberar                                  |
| Orange   | Väntar på anslutning (transkribering i kö)     |

Högerklicka på ikonen för:
- **Start Recording** / **Stop Recording** — manuell kontroll
- **Cancel Transcription** — avbryt en pågående transkribering
- **Open Recordings** — öppnar mappen med inspelningar
- **Settings...** — öppnar `config.json` i din standardeditor
- **Quit** — avslutar programmet snyggt

Under inspelning visas en liten alltid-överst-panel dockad ovanför
systemfältets hörn med en pulserande **REC**-indikator, förfluten tid och
ljudnivåer i realtid för din mikrofon och övriga deltagare — dra den vart
du vill. En Windows-avisering visas när transkriberingen är klar.

### Konfiguration

Redigera `config.json` (skapas automatiskt vid första körningen):

| Nyckel           | Standard                     | Beskrivning                            |
| ---------------- | ---------------------------- | -------------------------------------- |
| `whisper_model`  | `"KBLab/kb-whisper-large"`   | Whisper-modell på berget.ai            |
| `llm_model`      | `"mistralai/Mistral-Small-3.2-24B-Instruct-2506"` | LLM för sammanfattning |
| `my_name`        | `"Me"`                       | Ditt namn i transkriptet               |
| `language`       | `"sv"`                       | Transkriberingsspråk                   |
| `keep_audio`     | `false`                      | Behåll WAV-filer efter transkribering  |
| `min_seconds`    | `30`                         | Släng inspelningar kortare än så här   |
| `output_dir`     | `"~/Recordings"`             | Var inspelningarna sparas              |
| `api_base_url`   | `"https://api.berget.ai/v1"` | API-adress                             |
| `prompt`         | *(facktermer)*               | Ordlista som förbättrar träffsäkerheten |

### Facktermer

Fältet `prompt` i `config.json` hjälper modellen att känna igen
ämnesspecifika termer. Anpassa det till din arbetsvardag:

```json
"prompt": "Power BI, SQL Server, SSIS, SSRS, SSAS, Azure DevOps, DAX, T-SQL, ETL..."
```

Lägg till eller ta bort termer efter behov. Whispers prompt-fält rymmer
max 224 tokens — standardlistan använder 213. Ingen omstart behövs —
konfigurationen läses på nytt vid varje inspelning.

---

## Felsökning

**Inget händer när jag dubbelklickar på `setup.bat`, eller så står det att
Python inte hittades.**
Python är inte installerat, eller så bockades inte "Add python.exe to
PATH" i under installationen. Installera om Python från
[python.org](https://www.python.org/downloads/), se till att bocka i rutan,
och kör `setup.bat` igen.

**Jag startade programmet men ingen ikon syns i systemfältet.**
Om du inte har angett någon API-nyckel ännu visas en ruta som ber dig köra
`setup.bat`. Ikonen kan också vara dold — klicka på den lilla uppåtpilen
(^) i systemfältet för att visa dolda ikoner.

**Transkriberingen misslyckas eller ikonen förblir blå.**
Kontrollera internetanslutningen och att din berget.ai-nyckel är giltig
och har saldo. Välj **Cancel Transcription** i menyn och försök igen.
Tekniska detaljer skrivs till `recorder.log` i programmappen.

**Spåret "Others" innehåller musik eller ljud från andra program.**
Loopback fångar *allt* systemljud. Stäng av ljudet i andra program
(webbläsare, musik) under möten.

---

## Vanliga frågor

**Behöver jag en kraftfull dator?**
Nej. All tung bearbetning sker på berget.ai:s servrar. Vilken modern
Windows-dator som helst fungerar.

**Kostar det pengar?**
Programmet är gratis. berget.ai tar en liten slant per minut ljud (se
API-kostnad under Tekniska detaljer — ungefär 0,09 EUR för ett
30-minutersmöte). Du behöver ett konto hos berget.ai.

**Var sparas mina inspelningar?**
I mappen `Recordings` i din användarmapp som standard. Välj
**Open Recordings** i menyn för att hoppa direkt dit.

**Kan det spela in utan att jag klickar på Start?**
Nej — inspelning är alltid manuell, det är en medveten design. Du
bestämmer när det spelas in.

**Lämnar mitt ljud datorn?**
Bara ljudet skickas till berget.ai för transkribering. Se noteringen om
integritet högst upp.

**Vad händer om jag är offline när mötet slutar?**
En avisering berättar att inspelningen är sparad och att transkriberingen
startar automatiskt så fort du är online igen (kollas var 15:e sekund) —
ikonen i systemfältet är orange under väntan.
Det överlever omstarter: stänger du programmet eller datorn innan dess
plockas inspelningen upp och transkriberas nästa gång programmet startar.
**Cancel Transcription** avbryter väntan — en avbruten inspelning
transkriberas aldrig automatiskt, men ljudet behålls så att du kan köra
`retranscribe.py` manuellt.

---

## Tekniska detaljer

- **Ingen manuell ffmpeg-installation** — ljudkonverteringen använder
  ffmpeg-binären som följer med paketet `imageio-ffmpeg` och installeras
  automatiskt under setup.
- **Talaridentifiering** bygger på två separata strömmar (mikrofon
  respektive loopback) i stället för en diariseringsmodell. Det skiljer
  dig från "Others" men identifierar inte enskilda deltagare på distans.
- **WASAPI-loopback** fångar allt systemljud, inte bara mötesappen. Om
  andra program spelar ljud under samtalet hamnar det i
  "Others"-strömmen.
- **Offlinedetektering** — när du stoppar en inspelning avgör en snabb
  TCP-koll mot API-värden om transkriberingen startar direkt eller
  väntar. Under väntan kollas anslutningen var 15:e sekund och
  transkriberingen återupptas automatiskt. Nya inspelningar kan inte
  startas förrän väntan är klar eller avbruten.
- **Väntemarkör** — en `.pending`-fil i inspelningsmappen markerar att en
  transkribering återstår. Den tas bort vid lyckat resultat eller
  avbrytning och behålls vid fel eller avstängning, så att programmet
  återupptar ofärdiga transkriberingar vid nästa start. `retranscribe.py`
  rensar den också.
- **Transkribering i bitar** — ljudfiler delas i 2-minutersbitar,
  konverteras till mp3 och skickas en i taget med automatiska
  omförsök. Det undviker API-timeouts vid långa inspelningar.
- **Inspelningspanel** — ett ramlöst alltid-överst tkinter-fönster
  (rundade hörn via genomskinlig färgnyckel) med pulserande REC-prick,
  tidräknare och nivåstaplar i realtid för mikrofon och loopback; dockat
  i arbetsytans nedre högra hörn, flyttbart.
- **API-kostnad** — transkribering kostar ca 0,00005 EUR/sekund
  (ca 0,09 EUR för ett 30-minutersmöte). LLM-sammanfattningen kostar
  bråkdelar av ett öre per möte.
- Inspelningar kortare än `min_seconds` slängs automatiskt.
- Om transkriberingen avbryts eller misslyckas behålls råljudet (`mic.wav`,
  `loopback.wav`) i inspelningsmappen — även när `keep_audio` är false —
  så att du kan slutföra senare med
  `python retranscribe.py "<inspelningsmapp>"`.
- Två API-nycklar stöds: `BERGET_API_KEY` för whisper, `BERGET_API_KEY2`
  för LLM:en (faller tillbaka på `BERGET_API_KEY` om den inte är satt).

---

## Ändringslogg

### v1.6.0 (2026-06-11)
- Nytt: ljudnivåfönstret är nu en inspelningspanel — ramlös och mörk,
  dockad ovanför systemfältets hörn, med pulserande REC-prick, förfluten
  inspelningstid och tunna nivåstaplar för mikrofon och deltagare.
  Flyttbar som tidigare

### v1.5.2 (2026-06-11)
- Nytt: ett eget orange ikonläge visar när programmet väntar på
  internetanslutning (gick tidigare inte att skilja från transkribering),
  och verktygstipset visar hur många inspelningar som står i kö vid en
  återupptagning. **Cancel Transcription** fungerar även i det orangea
  läget

### v1.5.1 (2026-06-11)
- Nytt: ofärdiga transkriberingar överlever nu omstarter. Inspelningar
  som väntar på transkribering markeras på disk (`.pending`) och
  återupptas automatiskt nästa gång programmet startar — till exempel om
  du fäller ihop datorn medan du är offline. Avbrytning tar bort
  markeringen (en avbruten inspelning transkriberas aldrig automatiskt);
  `retranscribe.py` rensar den efter manuell återställning
- Aviseringarna vid offline och fel ber dig inte längre hålla programmet
  igång eller köra `retranscribe.py` — återställningen är automatisk

### v1.5.0 (2026-06-11)
- Nytt: stoppar du en inspelning utan internet visas direkt en avisering
  om att transkriberingen väntar, och den startar automatiskt så fort du
  är online igen (anslutningen kollas var 15:e sekund; **Cancel
  Transcription** fungerar under väntan och ljudet behålls alltid)

### v1.4.2 (2026-06-11)
- Fix: en misslyckad transkribering (till exempel utan internet) visar nu
  en avisering om att ljudet är sparat och hur det räddas med
  `retranscribe.py` — tidigare gick programmet tyst tillbaka till viloläge
  utan besked
- Fix: kvarlämnade WAV-bitar städas nu bort även när transkriberingen
  misslyckas halvvägs (tidigare bara vid avbrytning)

### v1.4.1 (2026-06-04)
- Fix: när en lång inspelning sparades kunde det ta flera minuter medan
  ikonen fortfarande visade rött ("Recording"); ett extra klick på Stop
  under den tiden avbröt transkriberingen och slängde ljudet. Ikonen visar
  nu "bearbetar" direkt när Stop trycks, extra klick under sparandet
  ignoreras, och avbrutna transkriberingar **behåller** numera ljudet så
  att det kan räddas med `retranscribe.py` i stället för att raderas
- Fix: kvarlämnade WAV-bitar städas nu bort när transkriberingen avbryts

### v1.4.0 (2026-06-02)
- Guidad installation i ett steg via `setup.bat`: kontrollerar Python,
  skapar miljön, installerar beroenden och sparar din API-nyckel
- ffmpeg följer nu med automatiskt (`imageio-ffmpeg`) — ingen manuell
  installation
- Vänlig dialogruta vid första körningen om API-nyckeln saknas (tidigare
  avslutades programmet tyst utan besked)
- Konsollfönstren som blinkade till under transkribering visas inte längre
- La till `.env.example`, en MIT-`LICENSE` och en publik README med
  felsökning och vanliga frågor
- Loggfiler versionhanteras inte längre

### v1.3.0 (2026-06-02)
- Flytande VU-mätarfönster visar ljudnivåer för mikrofon och loopback i
  realtid under inspelning
- Autostart vid Windows-inloggning via genväg i Autostart
- Transkribering i mp3-bitar med omförsök för stabilare API-anrop (stora
  filer delas i 2-minutersbitar)
- Stöd för att avbryta pågående inspelning och transkribering
- Beskrivande filnamn på transkript utifrån LLM-genererad mötestitel
- Faller snyggt tillbaka på råtranskript om LLM-sammanfattningen
  misslyckas
- Fix: hantera tomma ljudramar utan krasch
- Fix: VU-mätarens trådning och upprensning vid stopp

### v1.2.0 (2026-03-26)
- LLM-efterbearbetning: strukturerad markdown med sammanfattning, beslut,
  åtgärdspunkter och renskrivna mötesanteckningar
- Konfigurerbart talarnamn (`my_name` i konfigurationen)
- Stöd för separat API-nyckel för LLM-anropen (`BERGET_API_KEY2`)
- Utökad ordlista med facktermer (213/224 Whisper-tokens)
- Startfilen bytte namn till `Recorder.bat`

### v1.1.0 (2026-03-26)
- Byte från lokal Whisper till berget.ai:s API (kb-whisper-large)
- Manuell start/stopp av inspelning via menyn i systemfältet
- Ordlista med facktermer via `prompt` i konfigurationen
- Fix för distorsion i loopback-ljudet (nedmixning till stereo)
- ffmpeg-beroendet borttaget
- Tidsstämplar borttagna ur transkriptet

### v1.0.0 (2026-03-26)
- Första utgåvan
- Inspelning av två strömmar (mikrofon + loopback)
- Transkript med talaretiketter
- Programikon i systemfältet med statusfärger
- Windows-aviseringar när transkriberingen är klar
- Konfigurerbar via `config.json`
