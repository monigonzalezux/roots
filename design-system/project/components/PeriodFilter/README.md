# PeriodFilter

Quiet pills for the time range, labelled Período.

Deliberately lighter than `SegmentedControl` so the two never compete. The selected range gets a soft musgo fill. When the chosen period is empty, pair it with an `AlertBar` that offers "Ver todo".

The consumer provides: a `.tbar` with a `.caps` label and `.tchip` buttons using `aria-pressed`.
