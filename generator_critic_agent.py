class GeneratorCriticAgent:
    def __init__(self, config=None):
        self.config = config or {}

    def score(self, response, request):
        # Always return perfect score for now
        return 1.0
