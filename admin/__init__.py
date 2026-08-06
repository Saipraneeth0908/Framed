"""Admin application.

A separate deployable on a separate hostname with its own cookie, its own
secret and its own database role (admin_app). It imports nothing from web/ --
only db/ and common/. That rule is what makes the isolation real: a routing bug
in the storefront cannot expose an admin route, because the admin routes are not
in that process at all.
"""
