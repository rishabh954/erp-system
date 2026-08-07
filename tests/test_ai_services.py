"""
Tests for AI Services in ERP system.
"""
import pytest
from unittest.mock import patch, MagicMock
from django.conf import settings

from apps.ai.services import (
    LLMService,
    _get_openai,
    _get_gemini,
    AI_NOT_CONFIGURED_MSG,
    ExpenseCategorisationService
)
from apps.ai.models import AIConfiguration

@pytest.mark.django_db
class TestAIServices:
    def test_when_no_key_set_returns_not_configured(self, company):
        """Test: when no key set returns AI_NOT_CONFIGURED_MSG"""
        AIConfiguration.objects.filter(company=company).delete()
        with patch('apps.ai.services.getattr') as mock_getattr:
            mock_getattr.side_effect = lambda name, default=None: "" if name in ("OPENAI_API_KEY", "GEMINI_API_KEY") else getattr(settings, name, default)
            response, tokens = LLMService.chat([{"role": "user", "content": "Hello"}], company=company)
            assert response == AI_NOT_CONFIGURED_MSG
            assert tokens == 0

    def test_get_gemini_returns_client(self, company):
        """Test: when company has gemini key set, _get_gemini returns client"""
        AIConfiguration.objects.create(company=company, gemini_api_key="test-gemini-key")
        with patch('google.generativeai.GenerativeModel') as mock_model, \
             patch('google.generativeai.configure') as mock_configure:
            client = _get_gemini(company)
            mock_configure.assert_called_once_with(api_key="test-gemini-key")
            assert client == mock_model.return_value

    def test_chat_with_mock_openai_response(self, company):
        """Test: chat() with mock OpenAI response"""
        AIConfiguration.objects.create(company=company, openai_api_key="test-key")
        
        with patch('apps.ai.services._get_openai') as mock_get_openai:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices[0].message.content = "OpenAI response"
            mock_response.usage.total_tokens = 42
            mock_client.chat.completions.create.return_value = mock_response
            mock_get_openai.return_value = mock_client
            
            response, tokens = LLMService.chat([{"role": "user", "content": "Hello"}], company=company)
            
            assert response == "OpenAI response"
            assert tokens == 42
            mock_client.chat.completions.create.assert_called_once()

    def test_chat_falls_back_to_gemini_when_openai_fails(self, company):
        """Test: chat() falls back to Gemini when OpenAI fails"""
        AIConfiguration.objects.create(company=company, openai_api_key="test-key", gemini_api_key="test-gemini")
        
        with patch('apps.ai.services._get_openai') as mock_get_openai, \
             patch('apps.ai.services._get_gemini') as mock_get_gemini:
            
            mock_openai_client = MagicMock()
            mock_openai_client.chat.completions.create.side_effect = Exception("OpenAI down")
            mock_get_openai.return_value = mock_openai_client
            
            mock_gemini_client = MagicMock()
            mock_gemini_response = MagicMock()
            mock_gemini_response.text = "Gemini fallback response"
            mock_gemini_client.generate_content.return_value = mock_gemini_response
            mock_get_gemini.return_value = mock_gemini_client
            
            response, tokens = LLMService.chat([{"role": "user", "content": "Hello"}], company=company)
            
            assert response == "Gemini fallback response"
            assert tokens == 0

    def test_expense_categorisation_fallback(self):
        """Test: ExpenseCategorisationService.categorise() fallback keyword matching when no AI."""
        descriptions = ["Uber ride", "Team lunch", "AWS cloud", "printer paper", "Random unknown"]
        
        with patch('apps.ai.services.LLMService.chat') as mock_chat:
            mock_chat.return_value = ("Invalid format", 0)
            
            results = ExpenseCategorisationService.categorise(descriptions)
            
            assert len(results) == 5
            categories = [r['category'] for r in results]
            assert categories[0] == "Travel & Transport"
            assert categories[1] == "Meals & Entertainment"
            assert categories[2] == "Software & Subscriptions"
            assert categories[3] == "Office Supplies"
            assert categories[4] == "Other"
