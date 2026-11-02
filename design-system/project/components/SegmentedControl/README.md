# SegmentedControl

Switches the whole view between types of sale: Todo, Directo, Negocios.

It is the loudest filter on a page and always sits **above** time filters (`PeriodFilter`). Counts in the `.n` badge are optional. At phone width it stretches to full width with equal segments.

The consumer provides: a `.segctl` group (`role="group"`, an `aria-label`) of `<button>`s with `aria-pressed`.
