import os
import ssl
from dotenv import load_dotenv
from crewai import Agent, Crew, Process, Task, LLM
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List
from bug_builder import app_config, athena_token
config = app_config

load_dotenv()

# Temporary workaround for corporate TLS interception.
# Insecure: disable once proper CA trust is configured.
def _insecure_ssl_context(*args, **kwargs):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


ssl.create_default_context = _insecure_ssl_context
ssl._create_default_https_context = ssl._create_unverified_context

@CrewBase
class BugBuilder():
    """BugBuilder crew"""

    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    agents: List[BaseAgent]
    tasks: List[Task]

    llm = LLM(
        model=config["llm"]["model"],
        api_key=athena_token,
        base_url=config["llm"]["base_url"],
    )

    # Bug tracking agents
    @agent
    def bug_report_specialist(self) -> Agent:
        return Agent(
            config=self.agents_config['bug_report_specialist'],
            verbose=True,
            llm=self.llm
        )

    @agent
    def youtrack_url_generator(self) -> Agent:
        return Agent(
            config=self.agents_config['youtrack_url_generator'],
            verbose=True,
            llm=self.llm
        )

    @agent
    def testcase_bug_report_specialist(self) -> Agent:
        return Agent(
            config=self.agents_config['testcase_bug_report_specialist'],
            verbose=True,
            llm=self.llm
        )

    # Bug tracking tasks
    @task
    def generate_bug_report(self) -> Task:
        return Task(
            config=self.tasks_config['generate_bug_report'],
            output_file='bug_report.md'
        )

    @task
    def generate_youtrack_url(self) -> Task:
        return Task(
            config=self.tasks_config['generate_youtrack_url'],
            output_file='youtrack_url.txt'
        )

    @task
    def generate_testcase_bug_report(self) -> Task:
        return Task(
            config=self.tasks_config['generate_testcase_bug_report'],
            output_file='bug_report.md'
        )

    @crew
    def crew(self, mode='gherkin') -> Crew:
        """Creates the BugBuilder crew with mode-specific tasks"""
        normalized_mode = (mode or 'gherkin').strip().lower()
        if normalized_mode in {'testcase', 'testcases'}:
            tasks = [self.generate_testcase_bug_report(), self.generate_youtrack_url()]
        else:
            tasks = [self.generate_bug_report(), self.generate_youtrack_url()]
        
        return Crew(
            agents=[
                self.bug_report_specialist(),
                self.testcase_bug_report_specialist(),
                self.youtrack_url_generator(),
            ],
            tasks=tasks,
            process=Process.sequential,
            verbose=True,
        )
