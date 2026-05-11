import feedparser

def get_headlines_rss(url, limit=10):
    """
    Extrae titulares desde un feed RSS.
    Args:
        url (str): URL del feed RSS
        limit (int): Cantidad máxima de titulares
    Returns:
        list[str]: Lista de titulares
    """
    feed = feedparser.parse(url)
    headlines = [entry.title for entry in feed.entries[:limit]]
    return headlines

def get_all_headlines():
    """
    Combina titulares de Ámbito y Cronista.
    Returns:
        list[str]: Lista combinada de titulares
    """
    ambito_url = "https://www.ambito.com/rss/economia.xml"
    cronista_url = "https://www.cronista.com/rss/finanzasmercados.xml"
    ambito_headlines = get_headlines_rss(ambito_url)
    cronista_headlines = get_headlines_rss(cronista_url)
    return ambito_headlines + cronista_headlines

if __name__ == "__main__":
    headlines = get_all_headlines()
    print(f"📰 Se encontraron {len(headlines)} titulares.")
    for i, h in enumerate(headlines, 1):
        print(f"{i}. {h}")
