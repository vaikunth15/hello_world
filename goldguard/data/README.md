# data/ — Market & Macro Adapters

## Invariants

- All adapters sit behind protocols (`BarSource`, `MacroSource`); strategies
  and the risk engine never import an adapter — they receive plain
  `Bar`/`MacroState` values.
- Bars must be strictly increasing in time with consistent OHLC; loaders
  raise instead of passing through broken data.
- All timestamps are timezone-aware. Naive timestamps are rejected.
- Missing macro data fails **closed**: `MacroState` fields default to `None`
  and the regime filters return False, which means no trade.
- Macro series: FRED `DFII10` (10Y TIPS real yield) and `DTWEXBGS`
  (broad dollar index, the DXY proxy).
