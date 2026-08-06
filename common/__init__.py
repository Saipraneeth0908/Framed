"""Code shared by web/, admin/, collector/ and worker/.

Deliberately tiny. admin/ imports nothing from web/ except this package and db/ --
that rule is what keeps the two deployables independent.
"""
