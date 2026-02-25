
stario.dev
Validation With Datastar
~2 minutes
Form Validation ¶

Stario + Datastar allow for instant, server-side validation without page refreshes.
1. The Frontend ¶

Bind your inputs to signals and use data.show to display errors.

async def home(c: Context, w: Writer):
    w.html(
        Form(
            data.signals({"user": "", "errors": {}}),
            Input(data.bind("user")),
            P(data.show("$errors.user"), data.text("$errors.user"), {"class": "err"}),
            Button(data.on("click", at.post("/save")), "Submit")
        )
    )

2. The Backend ¶

Validate the signals and sync any errors back to the client.

async def handle_save(c: Context, w: Writer):
    signals = await c.signals()
    user = signals.get("user", "")

    errors = {}
    if len(user) < 3:
        errors["user"] = "Too short!"

    if errors:
        return w.sync({"errors": errors})

    # Process valid data...
    await db.save(user)
    w.patch(Div("Saved!"))

Live Validation (Debounced) ¶

To validate as the user types, add an action to the input with a debounce.

Input(
    data.bind("user"),
    data.on("input", at.get("/validate"), debounce=0.3) # 300ms delay
)

This keeps the server from being overwhelmed by every keystroke while providing instant feedback to the user.

Changing the world, one byte at a time
