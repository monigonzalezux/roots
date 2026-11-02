# Field

A labelled input with an optional hint and its error line.

Labels sit above the input in 13.5px bold; optional fields say "(opcional)" in the label. Errors turn the border `bad` and explain how to fix it, in voseo: "Escribí tu correo."

The consumer provides: `.field` with a `<label for>` and an `.inp`; on error add `.bad` to the input and a `.err` line.
