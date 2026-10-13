import { CommandCenter } from "@/components/command-center/CommandCenter";
import { RoleHome } from "@/components/shell/RoleHome";

export default function Home() {
  return (
    <RoleHome>
      <CommandCenter />
    </RoleHome>
  );
}
