
import { BrowserRouter } from "react-router-dom";
import AppRouter from "./app/routing/AppRouter";
import { AppProvider } from "./app/providers/AppProvider";

export default function App() {
  return (
    <BrowserRouter>
      <AppProvider>
        <AppRouter />
      </AppProvider>
    </BrowserRouter>
  );
}
