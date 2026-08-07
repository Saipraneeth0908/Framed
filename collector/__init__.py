"""Write-only event collector.

Its own hostname and its own process so it can be rate-limited and scaled
independently -- and so that if it dies, the storefront does not notice. It
holds the `ingest` database role, which can write raw.events and nothing else.
"""
