"""The `server` domain: serving the web application as a supervised process (web.md § 4).

It never imports the web package, as no domain imports a surface: the supervisor
starts it as a child process, `python -m femkit.web`.
"""
