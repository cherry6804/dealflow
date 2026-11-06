
import { BrowserRouter } from "react-router-dom";
import AppRouter from "./app/routing/AppRouter";
import { AppProvider } from "./app/providers/AppProvider";
import { ThemeProvider } from "./theme/ThemeProvider";

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <AppProvider>
          <AppRouter />
        </AppProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}
