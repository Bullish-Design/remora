
stario.dev
Html
2–3 minutes
HTML Reference ¶

Stario includes a type-safe HTML builder. No templates, no string concatenation - just Python functions.
Basic Usage ¶

from stario.html import Div, H1, P, A

def greeting(name: str):
    return Div(
        H1(f"Hello, {name}!"),
        P("Welcome to Stario."),
        A({"href": "/docs"}, "Read the docs"),
    )

Syntax Rules ¶

    Dictionaries -> Attributes
    Everything else -> Children (Strings, Elements, Lists, or None)

Div("Hello")                              # <div>Hello</div>
Div({"class": "container"}, "Hello")      # <div class="container">Hello</div>
Div(H1("Title"), P("Body"))              # Nested
Div({"class": "a"}, {"id": "b"}, "Hi")    # Merged attributes

Attributes ¶
Type 	Python 	Result
String 	{"id": "main"} 	id="main"
Boolean 	{"disabled": True} 	disabled
List 	{"class": ["a", "b"]} 	class="a b"
Style Dict 	{"style": {"color": "red"}} 	style="color:red;"
Nested 	{"data": {"id": 1}} 	data-id="1"
Security: Automatic Escaping ¶

All strings are escaped by default to prevent XSS.

Div('<script>alert(1)</script>')
# <div>&lt;script&gt;alert(1)&lt;/script&gt;</div>

Trusted Content (SafeString) ¶

Use SafeString only for content you trust (e.g., SVGs).

from stario.html import SafeString
Div(SafeString("<svg>...</svg>"))

Common Patterns ¶
Conditional Rendering ¶

None and False are ignored during rendering.

Div(
    H1("User"),
    Span("Admin") if user.is_admin else None
)

Lists ¶

Ul(*[Li(u.name) for u in users])

Components ¶

def card(title, body):
    return Div({"class": "card"},
        Div({"class": "header"}, H3(title)),
        Div({"class": "body"}, body)
    )

Rendering ¶

The Writer handles rendering via w.html(el). To get a raw string:

from stario.html import render
html_str = render(Div("Hi"))

Changing the world, one byte at a time
