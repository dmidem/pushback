# run slow tests last
def pytest_collection_modifyitems(session, config, items):
    slow = [i for i in items if i.get_closest_marker("slow")]
    rest = [i for i in items if i not in slow]
    items[:] = rest + slow
