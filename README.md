# MTEC Blender MCP Bridge

End-to-end guide to run Codex (eller annan MCP-klient) mot Blender med FastMCP.

![Riggad figur i Blender](doc/rig-demo.png)

## Innehåll
- Vad som startas
- Snabbstart (från tom maskin)
- Daglig start
- Konfiguration
- Felsökning
- Säkerhet

## Vad som startas
- Blender‑addon: `MTECBlenderBridge.py` – körs i Blender, exponerar HTTP på `http://127.0.0.1:8765`.
- Extern MCP‑server: `mtec_codex_mcp_server.py` – körs i Python/venv, pratar stdio med MCP-klient och HTTP med Blender.
- MCP‑klient: t.ex. Codex/VS Code med en MCP-profil som startar servern via stdio.

## Snabbstart (ny maskin)
```powershell
git clone <repo-url>
cd BlenderMCP
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# (valfritt) kopiera config:
copy mtec-blender.example.json mtec-blender.json
```
I Blender: Installera och aktivera `MTECBlenderBridge.py` som addon (Edit -> Preferences -> Add-ons -> Install).

## Daglig start (befintlig miljö)
1) Blender
   - Öppna Blender, se till att addon är aktiverad.
   - Panel `MTEC MCP` -> klicka `Start MTEC Bridge`.
2) Terminal i projektroten
   - `.venv\Scripts\Activate.ps1`
   - `.venv\Scripts\python.exe .\mtec_codex_mcp_server.py`
3) MCP‑klient
   - Använd profilen `mtec-blender` (kopian av `mtec-blender.example.json`).
   - Anslut; loggen i terminalen ska visa att klienten kopplar upp.

## Konfiguration
- Template: `mtec-blender.example.json` (checkad in).
- Personlig: `mtec-blender.json` (git-ignorerad). Uppdatera `command`/`args` om din Python/venv ligger på annan plats.
- Miljövariabler (valfritt):
  - `MTEC_BLENDER_BRIDGE_URL` – ändra om bryggan lyssnar på annan host/port.
  - `MTEC_BLENDER_BRIDGE_TIMEOUT` – sekunder för långkörande tool calls.

## Hälsokontroller
- Blender-brygga: `http://127.0.0.1:8765/health`
- Verktygslista: `http://127.0.0.1:8765/tools`

## Vanliga fel
- “.venv is not recognized”: skapa venv och aktivera med `.venv\Scripts\Activate.ps1`.
- MCP-klient hittar inte servern: kontrollera att `command` i `mtec-blender.json` pekar på rätt Python och att terminalen med servern är öppen.
- Kan inte nå Blender: addon ej startad eller fel port; klicka `Start MTEC Bridge` och kolla `/health`.

## Säkerhet
- `run_python_snippet` kör kod direkt i Blender; använd bara i betrodda lokala miljöer.
- HTTP‑bryggan lyssnar på localhost; exponera den inte publikt.

## Versionsinfo
- FastMCP: 3.2.4
- httpx: 0.28.1
