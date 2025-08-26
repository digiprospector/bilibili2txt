from scrape import scrape
from client_in_queue import in_queue


def main():
    scrape()
    in_queue()

if __name__ == "__main__":
    main()