from assistant.brain import train

if __name__ == "__main__":
    vocab, examples = train()
    print(f"Димасик обучен. Словарь: {vocab}, обучающих пар: {examples}.")
