# StatusPill

Shows an order's state with its color and its name.

Colors are reserved for states: verificar `warn`, pagado `info`, enviado `pur`, entregado `ok`, rechazado `bad`. Never color alone: the pill always carries the state's name.

The consumer provides: `<span class="pill st-<state>">` with the state's label.
