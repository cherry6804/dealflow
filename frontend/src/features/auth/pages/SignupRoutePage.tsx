import { Navigate, useSearchParams } from "react-router-dom";

import SibvoSignInRedirectPage from "./SibvoSignInRedirectPage";

export default function SignupRoutePage() {
  const [searchParams] = useSearchParams();
  const invitationToken = searchParams.get("invitation")?.trim();

  if (!invitationToken) {
    return <SibvoSignInRedirectPage />;
  }

  return (
    <Navigate
      replace
      to={`/accept-invitation?token=${encodeURIComponent(invitationToken)}`}
    />
  );
}
