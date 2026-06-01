# -*- coding: utf-8 -*-
import sys
from pathlib import Path

_EXAM_GEN_DIR = Path(__file__).resolve().parent.parent.parent / "Test_to_Test_Paper_Generation"
if str(_EXAM_GEN_DIR) not in sys.path:
    sys.path.insert(0, str(_EXAM_GEN_DIR))

import pytest
import json
import os
import shutil

from exam_generator.config_loader import load_config
from exam_generator.knowledge_manager import KnowledgeManager
from exam_generator.pipeline import ExamGenerationPipeline
from exam_generator.agents.base import BaseAgent
from exam_generator.agents.analyzer import KnowledgeAnalyzer
from exam_generator.agents.scenario import ScenarioGenerator
from exam_generator.agents.generator import QuestionGenerator
from exam_generator.agents.assembler import ExamAssembler

def test_config_loader_placeholder(monkeypatch):
    config_content = """
api:
  active_provider: "${MOCK_PROVIDER:-fallback}"
  ds_key: "${MOCK_KEY:-}"
"""
    config_file = Path("D:/project/testpaper/.tmp_test_config.yaml")
    config_file.write_text(config_content, encoding="utf-8")
    
    try:
        # CASE 1: No environment variables, should use fallback/empty defaults
        monkeypatch.delenv("MOCK_PROVIDER", raising=False)
        monkeypatch.delenv("MOCK_KEY", raising=False)
        cfg = load_config(str(config_file))
        assert cfg["api"]["active_provider"] == "fallback"
        assert cfg["api"]["ds_key"] == ""
        
        # CASE 2: Set environment variables
        monkeypatch.setenv("MOCK_PROVIDER", "real_deal")
        monkeypatch.setenv("MOCK_KEY", "real_key")
        cfg2 = load_config(str(config_file))
        assert cfg2["api"]["active_provider"] == "real_deal"
        assert cfg2["api"]["ds_key"] == "real_key"
    finally:
        if config_file.exists():
            config_file.unlink()


def test_knowledge_manager_default_path():
    km = KnowledgeManager()
    assert km.data is not None
    assert len(km.get_topics_summary()) > 0


def test_agents_prompt_switching(monkeypatch):
    mock_config = {
        "api": {
            "active_provider": "ds",
            "ds_key": "dummy",
            "ds_base_url": "dummy"
        },
        "models": {
            "analyzer": "dummy",
            "scenario": "dummy",
            "generator": "dummy",
            "assembler": "dummy",
            "pdf_parser": "dummy"
        },
        "temperature": {
            "analyzer": 0.1,
            "scenario": 0.1,
            "generator": 0.1,
            "assembler": 0.1,
            "pdf_parser": 0.1
        },
        "prompts": {
            "analyzer": "v1",
            "scenario": "v2",
            "generator": "v1",
            "assembler": "v2"
        }
    }
    
    # Mock OpenAI client initialization inside BaseAgent
    monkeypatch.setattr("exam_generator.agents.base.OpenAI", lambda *a, **k: None)
    
    # Test Analyzer with v1 prompt
    analyzer = KnowledgeAnalyzer(config=mock_config)
    assert "教研专家" in analyzer.system_prompt
    
    # Test Scenario with v2 prompt (dynamic)
    scenario = ScenarioGenerator(config=mock_config)
    assert "教育心理学" in scenario.system_prompt


def test_pipeline_backward_compatible_run(monkeypatch):
    test_output_dir = Path("D:/project/testpaper/.tmp_test_output")
    if test_output_dir.exists():
        shutil.rmtree(test_output_dir)
        
    mock_config = {
        "api": {
            "active_provider": "ds",
            "ds_key": "dummy",
            "ds_base_url": "dummy"
        },
        "models": {
            "analyzer": "dummy",
            "scenario": "dummy",
            "generator": "dummy",
            "assembler": "dummy",
            "pdf_parser": "dummy"
        },
        "temperature": {
            "analyzer": 0.1,
            "scenario": 0.1,
            "generator": 0.1,
            "assembler": 0.1,
            "pdf_parser": 0.1
        },
        "prompts": {
            "analyzer": "v2",
            "scenario": "v2",
            "generator": "v2",
            "assembler": "v2"
        },
        "paths": {
            "output_dir": str(test_output_dir)
        },
        "scenario_threshold": 6
    }
    
    # Mock BaseAgent OpenAI client
    monkeypatch.setattr("exam_generator.agents.base.OpenAI", lambda *a, **k: None)
    
    # Mock _call_llm for different agents to return mock JSON responses
    def mock_call_llm(self, user_message: str, *args, **kwargs):
        agent_name = getattr(self, "agent_name", "")
        # Detect if it's phase A (using pdf_parser model or matching prompts)
        if "topic_id" in str(user_message) or "A1-1" in str(user_message) or kwargs.get("agent_name") == "pdf_parser":
            return '{"topic_id": "A1-1"}'
        elif agent_name == "analyzer":
            return '{"key_points_hit": ["test_point"], "core_competencies": ["test_comp"], "key_math_ideas": ["test_idea"], "difficulty": "medium", "syllabus_compliance": {"status": "IN_SYLLABUS"}}'
        elif agent_name == "scenario":
            return '{"new_scenario": {"style": "life", "context": "mock scenario", "key_variables": {}}}'
        elif agent_name == "generator":
            return '{"new_questions": [{"id": "NQ-Q1", "ref_id": "Q1", "type": "单选题", "score": 5, "stem": "new stem", "options": ["A.1"], "answer": "A", "solution": "sol", "svg_code": null}]}'
        elif agent_name == "assembler":
            return 'mock full assembled text'
        return '{}'
        
    monkeypatch.setattr(BaseAgent, "_call_llm", mock_call_llm)
    
    try:
        pipeline = ExamGenerationPipeline(config=mock_config, max_workers=2)
        questions = [{
            "id": "Q1",
            "type": "单选题",
            "stem": "x+y=1",
            "options": ["A.1"],
            "answer": "A",
            "score": 5,
            "knowledge_points": ["algebra"]
        }]
        
        md_path = pipeline.run(questions=questions)
        assert os.path.exists(md_path)
        # Check pdf path companion
        pdf_path = os.path.splitext(md_path)[0] + ".pdf"
        assert os.path.exists(pdf_path)
    finally:
        if test_output_dir.exists():
            shutil.rmtree(test_output_dir)
