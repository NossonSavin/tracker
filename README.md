# Windows Stock Portfolio Tracker

A simple Windows app to track stock holdings, display portfolio value, and run from the system tray.

## Features
- Search for a stock by ticker symbol
- Enter number of shares you own
- View price, value, and total portfolio worth
- Updates automatically every 5 sec
- Hides to system tray when the window is closed

## Setup
1. Install Python 3.10+.
2. Open a terminal in this folder.
3. Install dependencies:

```powershell
pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

## Usage
- Enter a ticker symbol like `AAPL` and the number of shares.
- Click `Add / Update`.
- The window can be closed to hide it to the tray.
- Right-click the tray icon to show the window, refresh, or quit.
