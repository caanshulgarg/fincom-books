<div align="center">
  <img src="logo.png" alt="FinCom Books" width="96" height="96" />

  # FinCom Books

  **Offline, keyboard-first double-entry accounting with GST and inventory.**
</div>

## What it does

- **Vouchers** with function-key shortcuts: Contra `F4`, Payment `F5`, Receipt `F6`, Journal `F7`, Sales `F8`, Purchase `F9`, Credit/Debit Note; `Ctrl+A` accept, `Alt+G` Go To, `Alt+C` create a ledger inline.
- **GST**: CGST/SGST vs IGST by state, GSTR-1 (B2B, B2CL, B2CS, HSN) and GSTR-3B with JSON export for the GST portal.
- **Inventory**: stock items, godowns, batches, weighted-average valuation, bill of materials and manufacturing.
- **Banking**: bank reconciliation with clearing dates; bill-wise receivables and payables with credit limits.
- **Reports**: two-sided Balance Sheet and Profit & Loss, Trial Balance, Day Book, ledgers, Stock Summary, ratios.
- **Data**: Tally XML import/export, CSV/XLSX master templates, JSON backup and restore, company PIN lock, period lock.

Data stays on the computer in a local SQLite file (`%LOCALAPPDATA%\FinComBooks\data` on Windows, `~/Library/Application Support/FinComBooks/data` on macOS).

## Run it from source

Requires Python 3.9 or newer (and `openpyxl` only for XLSX templates).

```bash
python3 app_server.py --port 3543 --data ./data/books.sqlite3
```

Then open http://127.0.0.1:3543. On macOS you can also run `./launch_mac.sh`; on Windows, `Launch.bat`.

## Installers

Pushing a tag such as `v1.2.0` runs `.github/workflows/release.yml`, which builds `FinComBooksSetup.exe`, `FinComBooks_Portable.zip` and `FinComBooksSetup.dmg` and attaches them to a GitHub Release. The installers are not code-signed yet, so Windows SmartScreen and macOS Gatekeeper will warn on first launch.

## Tests

```bash
pip install pytest playwright openpyxl
python -m playwright install msedge
python -m pytest -q
```

## Known limitations

- **LAN mode** (`Launch.ps1 -Lan`) has no user login: anyone on the same network can open companies that have no PIN. Use it only on a trusted network.
- Each save rewrites the whole data file, so very large multi-year books slow down.
- No cloud sync yet.

## License

See [LICENSE](LICENSE).

Tally and TallyPrime are trademarks of Tally Solutions Pvt. Ltd. FinCom Books is not affiliated with or endorsed by Tally Solutions.
