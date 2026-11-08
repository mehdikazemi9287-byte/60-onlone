import CustomerOrders from '@/components/organization/CustomerOrders';
import{OrganizationRecords}from'@/components/organization/Dashboard';
export default function Page(){return <><CustomerOrders/><details><summary>اسناد خرید از تأمین‌کنندگان (مجزا از سفارش مشتری)</summary><OrganizationRecords kind="orders"/></details></>}
