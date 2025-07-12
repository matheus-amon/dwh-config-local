from datetime import datetime
from src.get_quotes import get_quotes


def test_get_quotes_success(monkeypatch):
    """Test successful API response with valid data."""
    class MockResponse:
        def json(self):
            return {
                "value": [
                    {"moeda": "USD", "cotacaoCompra": 5.2, "dataHoraCotacao": "2025-07-01"},
                    {"moeda": "USD", "cotacaoCompra": 5.3, "dataHoraCotacao": "2025-07-02"}
                ]
            }
    
    monkeypatch.setattr("src.get_quotes.requests.get", lambda url: MockResponse())
    
    start_date = datetime(2025, 7, 1)
    end_date = datetime(2025, 7, 2)
    
    result = get_quotes(start_date, end_date, ["USD"])
    
    assert len(result) == 2
    assert result[0]["moeda"] == "USD"
    assert result[0]["cotacaoCompra"] == 5.2


def test_get_quotes_empty_response(monkeypatch):
    """Test handling of empty API response."""
    class MockResponse:
        def json(self):
            return {"value": []}
    
    monkeypatch.setattr("src.get_quotes.requests.get", lambda url: MockResponse())
    
    start_date = datetime(2025, 7, 1)
    result = get_quotes(start_date, currencies=["USD"])
    
    assert result == []


def test_get_quotes_request_exception(monkeypatch):
    """Test error handling when API request fails."""
    def mock_get(url):
        raise Exception("Connection error")
    
    monkeypatch.setattr("src.get_quotes.requests.get", mock_get)
    
    start_date = datetime(2025, 7, 1)
    result = get_quotes(start_date, currencies=["USD"])
    
    assert result == []


def test_get_quotes_pagination(monkeypatch):
    """Test pagination functionality with multiple API calls."""
    call_count = 0
    
    def mock_get(url):
        nonlocal call_count
        call_count += 1
        
        class MockResponse:
            def json(self):
                if call_count == 1:
                    return {"value": [{"moeda": "USD", "cotacaoCompra": 5.2}] * 100}
                return {"value": []}
        
        return MockResponse()
    
    monkeypatch.setattr("src.get_quotes.requests.get", mock_get)
    
    start_date = datetime(2025, 7, 1)
    result = get_quotes(start_date, currencies=["USD"], top=100)
    
    assert len(result) == 100
    assert call_count == 2


def test_get_quotes_default_parameters(monkeypatch):
    """Test function behavior with default parameter values."""
    called_urls = []
    
    def mock_get(url):
        called_urls.append(url)
        
        class MockResponse:
            def json(self):
                return {"value": []}
        
        return MockResponse()
    
    monkeypatch.setattr("src.get_quotes.requests.get", mock_get)
    
    start_date = datetime(2025, 7, 1)
    get_quotes(start_date)
    
    assert len(called_urls) == 2
    assert any("USD" in url for url in called_urls)
    assert any("EUR" in url for url in called_urls)