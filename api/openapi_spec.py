OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "Portfolio Dashboard Agent API",
        "version": "1.0.0",
        "description": "REST API for portfolio screening, notes, alerts, holdings, and trade assessments.",
    },
    "servers": [{"url": "/api/v1"}],
    "paths": {
        "/health": {"get": {"summary": "API health check"}},
        "/config": {"get": {"summary": "Runtime configuration (provider, sync interval)"}},
        "/preferences": {
            "get": {"summary": "User preferences (Portfolio Fit + Tax & Trim + Buy/Sell Plan + ticker segments)"},
            "patch": {"summary": "Update user preferences"},
        },
        "/preferences/ticker-segments/export": {
            "get": {"summary": "Export named ticker segments as plain text backup"},
        },
        "/overview": {"get": {"summary": "Portfolio KPIs, holdings summary, and pastProgress (1M/3M/ATH)"}},
        "/symbols": {
            "get": {"summary": "List symbols"},
            "post": {"summary": "Create symbol"},
        },
        "/symbols/search": {
            "get": {"summary": "Ticker autocomplete search (Finnhub)"},
        },
        "/symbols/{symbol}": {
            "get": {"summary": "Symbol detail with notes"},
            "put": {"summary": "Update thresholds/prices"},
            "delete": {"summary": "Delete symbol"},
        },
        "/symbols/{symbol}/notes": {
            "get": {"summary": "List notes"},
            "post": {"summary": "Add note"},
        },
        "/symbols/{symbol}/notes/{noteId}": {
            "put": {"summary": "Update note"},
            "patch": {"summary": "Update note"},
            "delete": {"summary": "Delete note"},
        },
        "/symbols/{symbol}/notes/{noteId}/synthesize": {"post": {"summary": "Synthesize one note and persist result"}},
        "/symbols/{symbol}/notes/synthesize": {"post": {"summary": "Synthesize all notes for symbol"}},
        "/symbols/{symbol}/fib-levels": {"get": {"summary": "Fibonacci retracement levels"}},
        "/symbols/{symbol}/inspector": {"get": {"summary": "Full symbol context"}},
        "/symbols/{symbol}/proposal": {
            "get": {"summary": "Trading proposal (State/Trigger/Portfolio Fit scaffold)"}
        },
        "/symbols/{symbol}/fundamentals": {"get": {"summary": "Fundamentals + recent news snapshot"}},
        "/symbols/{symbol}/assess": {"post": {"summary": "Assess one symbol"}},
        "/portfolio": {"get": {"summary": "All symbols with details"}},
        "/holdings": {
            "get": {"summary": "List holdings"},
            "post": {"summary": "Create/update holding"},
        },
        "/holdings/{symbol}": {
            "put": {"summary": "Update holding"},
            "delete": {"summary": "Delete holding"},
        },
        "/import": {"post": {"summary": "Import JSON payload"}},
        "/import/file": {"post": {"summary": "Upload JSON, CSV, or TXT file"}},
        "/tax-trim/proposal": {
            "get": {"summary": "Tax-loss + winner-trim proposal (scores, pools, Match Loss)"},
            "post": {"summary": "Tax-loss + winner-trim proposal (scores, pools, Match Loss)"},
        },
        "/tax-trim/order-book": {
            "post": {"summary": "Capture qualified tax & trim sells as an order book"},
        },
        "/screen": {"get": {"summary": "Multi-factor screening (query: minUpside, nearFib, belowBuy, hasAlerts)"}},
        "/fib-proximity": {"get": {"summary": "Fibonacci proximity map for all symbols"}},
        "/alerts": {"get": {"summary": "List alerts (query: symbol, status)"}},
        "/alerts/evaluate": {"post": {"summary": "Sync prices and evaluate alerts"}},
        "/alerts/{alertId}/dismiss": {"post": {"summary": "Dismiss alert"}},
        "/assessments": {"get": {"summary": "Assessment history (query: symbol, limit)"}},
        "/assess": {"post": {"summary": "Assess portfolio or subset"}},
        "/sync": {"post": {"summary": "Sync prices and evaluate alerts"}},
    },
}
