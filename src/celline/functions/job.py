from celline.functions._base import CellineFunction


class Job(CellineFunction):
    def register(self) -> str:
        return "job"

    def call(self, project):
        print("Job management - implement functionality as needed")
        return project
