import os
from dotenv import load_dotenv
from crewai import Agent, Crew, Process, Task, LLM
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List
from bug_builder import app_config as config, athena_token

load_dotenv()

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

    @crew
    def crew(self) -> Crew:
        """Creates the BugBuilder crew"""
        return Crew(
            agents=self.agents,  # Automatically created by the @agent decorator
            tasks=self.tasks,    # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=True,
        )
