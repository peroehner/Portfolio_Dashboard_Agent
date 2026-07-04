from services.overview_service import watchlist_only_count


def test_watchlist_only_ignores_zero_quantity_holdings_rows():
    symbols = [
        {"symbol": "AAPL"},
        {"symbol": "NVDA"},
        {"symbol": "IONQ"},
    ]
    holdings = [
        {"symbol": "AAPL", "quantity": 10},
        {"symbol": "NVDA", "quantity": 0},
        {"symbol": "IONQ", "quantity": None},
    ]
    assert watchlist_only_count(symbols, holdings) == 2


def test_watchlist_only_counts_symbols_without_holdings_rows():
    symbols = [{"symbol": "AAPL"}, {"symbol": "CRSP"}]
    holdings = [{"symbol": "AAPL", "quantity": 5}]
    assert watchlist_only_count(symbols, holdings) == 1
