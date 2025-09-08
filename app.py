from core.config import BASE_URL, IDENTITY, PASSWORD
from storage.pocketbase import PocketBaseClient, PBError
from controller.app_controller import AppController
from gui.main_window import MainWindow


def main():
    client = PocketBaseClient(BASE_URL)
    try:
        client.login(IDENTITY, PASSWORD)
    except PBError as e:
        # Evitamos tkinter si no tenemos token
        print(f"Login error: {e}")
        return

    controller = AppController(client)
    ui = MainWindow(controller)
    ui.mainloop()


if __name__ == "__main__":
    main()