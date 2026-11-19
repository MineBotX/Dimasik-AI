from assistant.brain import train

if __name__ == "__main__":
    vocab, examples = train()
    print(f"Training complete. Vocabulary: {vocab}; training pairs: {examples}.")
