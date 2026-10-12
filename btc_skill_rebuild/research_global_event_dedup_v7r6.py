def globally_unique_events(weeks):
    return len(set(event for week in weeks for event in week))
