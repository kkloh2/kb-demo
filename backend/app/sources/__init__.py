"""Source systems and their hierarchies.

    models.py   source_system, hierarchy (with its levels), hierarchy_node
    service.py  create a source system, its hierarchy and root (with admins and users groups);
                manage the root groups' members
    router.py   /api/sources (platform admins)

PLATFORM is seeded at start-up (app.access.service.sync_reference); every other system is created
here. Modules that need a system (Doc Hub needs DOC_HUB with levels ROOT -> DOC_REPO) work once a
platform admin has created it.
"""
