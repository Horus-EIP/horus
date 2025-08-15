import {
    MdDashboard,
    MdPeople,
    MdAssignment,
    MdLibraryBooks,
    MdSettings,
    MdChat,
} from 'react-icons/md';
import Image from 'next/image';
import MenuLink from './menuLink/menuLink';

const menuItems = [
    {
        title: "Pages",
        list: [
            {
                title: "Dashboard",
                link: "/dashboard",
                icon: <MdDashboard/>,
            },
            {
                title: "Agents",
                link: "/agents",
                icon: <MdPeople/>,
            },
            {
                title: "Tasks",
                link: "/tasks",
                icon: <MdAssignment/>,
            },
            {
                title: "Chat",
                link: "/chat",
                icon: <MdChat/>,
            },
            {
                title: "Knowledge Store",
                link: "/knowledge-store",
                icon: <MdLibraryBooks/>,
            },
            {
                title: "Settings",
                link: "/dashboard/settings",
                icon: <MdSettings/>,
            },
        ]
    }
]

const Sidebar = () => {
    return (
        <div className="fixed top-6">
            <div className="flex items-center mb-6 gap-6">
                <Image
                    className="rounded-full"
                    src="/user.png"
                    alt=""
                    width="50"
                    height="50"
                />
                <div className="flex flex-col">
                    <span className="text-lg">User</span>
                    <span className="text-sm text-[var(--textSoft)]">
                        Admin</span>
                </div>
            </div>
            <ul className="list-none">
                {menuItems.map((cat)=> (
                    <li key={cat.title}>
                        <span className="text-[var(--textSoft)] font-bold text-md">
                            {cat.title}
                        </span>
                        {cat.list.map((item) => (
                            <MenuLink
                                item={item}
                                key={item.title}
                            />
                        ))}
                    </li>
                ))}
            </ul>
        </div>
    )
}
export default Sidebar;